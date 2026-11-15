"""Firecrawl web search connector for public job postings."""
from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.services.job_sources.base import (
    ConnectorResult,
    JobListing,
    JobSourceConnector,
    clean_text,
    parse_datetime,
)


class FirecrawlConnector(JobSourceConnector):
    key = "firecrawl"
    display_name = "Firecrawl web search"
    base_url = "https://firecrawl.dev"
    attribution = "Search results discovered with Firecrawl. Verify details and eligibility on the employer's application page."
    requires_credentials = True
    notes = "Searches public web job listings using the configured Firecrawl API key."

    def is_configured(self) -> bool:
        return bool(settings.FIRECRAWL_API_KEY)

    def not_configured_reason(self) -> str:
        return "Firecrawl search is disabled because FIRECRAWL_API_KEY is not configured."

    async def fetch(self, filters: dict, limit: int, prefs: dict | None = None) -> ConnectorResult:
        result = ConnectorResult(source_key=self.key, display_name=self.display_name)
        if not self.is_configured():
            result.skipped_reason = self.not_configured_reason()
            return result

        query = _build_query(filters)
        body = {
            "query": query,
            "limit": min(max(1, limit), settings.FIRECRAWL_MAX_RESULTS),
            "sources": [{"type": "web"}],
            "country": "IN" if _mentions_india(filters) else None,
            "location": ", ".join(filters.get("location") or []) or None,
            "scrapeOptions": {"formats": ["markdown"]},
        }
        body = {key: value for key, value in body.items() if value is not None}
        headers = {
            "Authorization": f"Bearer {settings.FIRECRAWL_API_KEY}",
            "Content-Type": "application/json",
        }
        try:
            timeout = httpx.Timeout(settings.JOB_HTTP_TIMEOUT_SECONDS * 3)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{settings.FIRECRAWL_BASE_URL.rstrip('/')}/search",
                    json=body,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            result.error = f"Firecrawl search failed (HTTP {exc.response.status_code})."
            return result
        except (httpx.HTTPError, ValueError) as exc:
            result.error = f"Firecrawl search request failed ({type(exc).__name__})."
            return result

        if not isinstance(data, dict) or data.get("success") is False:
            result.error = "Firecrawl returned an unsuccessful search response."
            return result
        payload = data.get("data") or {}
        hits = payload.get("web") if isinstance(payload, dict) else None
        if not isinstance(hits, list):
            result.error = "Firecrawl returned an unexpected search response shape."
            return result

        for index, hit in enumerate(hits):
            if not isinstance(hit, dict):
                continue
            url = hit.get("url") or (hit.get("metadata") or {}).get("sourceURL")
            if not _is_job_url(url):
                continue
            raw_title = clean_text(hit.get("title") or (hit.get("metadata") or {}).get("title"))
            title, company = _title_company(raw_title, url)
            if not title or not company:
                continue
            markdown = hit.get("markdown") or ""
            description = clean_text(hit.get("description") or markdown)[:12000]
            listing = JobListing(
                source_key=self.key,
                external_id=url,
                title=title,
                company=company,
                location=", ".join(filters.get("location") or []) or None,
                description=description,
                description_html=None,
                application_url=url,
                source_url=url,
                posted_at=parse_datetime((hit.get("metadata") or {}).get("publishedTime")),
                raw={"firecrawl_rank": index + 1, "metadata": hit.get("metadata") or {}},
            ).normalize()
            result.listings.append(listing)
            if len(result.listings) >= limit:
                break
        if not result.listings:
            result.warnings.append("Search returned no results that could be confidently identified as job application pages.")
        return result


def _build_query(filters: dict) -> str:
    role = " OR ".join(str(value).strip() for value in filters.get("role") or [] if str(value).strip())
    location = " OR ".join(str(value).strip() for value in filters.get("location") or [] if str(value).strip())
    parts = [role or "open roles"]
    if location:
        parts.append(location)
    parts.extend(["jobs careers apply", "job posting"])
    if filters.get("work_mode") and "remote" in filters["work_mode"]:
        parts.append("remote")
    days = filters.get("posted_within_days")
    if days:
        parts.append(f"posted within {days} days")
    return " ".join(parts)


def _mentions_india(filters: dict) -> bool:
    text = " ".join(str(value) for value in filters.get("location") or []).lower()
    return any(token in text for token in ("india", "bengaluru", "bangalore", "mumbai", "delhi", "chennai", "hyderabad", "pune"))


def _is_job_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    path = parsed.path.lower()
    host = parsed.hostname.lower()
    if any(token in host for token in ("google.", "bing.com", "firecrawl.dev")):
        return False
    # Search and category pages look like jobs but are not application forms.
    if any(token in path for token in ("-jobs-in-", "-job-search", "/q-", "/jobs-in-", "/search", "/job-search")):
        return False
    parts = [part for part in parsed.path.split("/") if part]
    if "greenhouse.io" in host:
        return len(parts) >= 3 and parts[-2] == "jobs" and parts[-1].isdigit()
    if "lever.co" in host:
        return len(parts) >= 2 and bool(re.fullmatch(r"[0-9a-f-]{20,}", parts[-1], re.IGNORECASE))
    if "ashbyhq.com" in host:
        return len(parts) >= 2 and (bool(re.fullmatch(r"[0-9a-f-]{20,}", parts[-1], re.IGNORECASE)) or "job" in parts[-1].lower())
    if "myworkdayjobs.com" in host or "workday.com" in host:
        return any(part == "job" for part in parts) and any(re.search(r"_[A-Z0-9]{5,}$", part) for part in parts)
    if "smartrecruiters.com" in host:
        return "job" in parts and len(parts) >= 3
    if "workable.com" in host:
        return "j" in parts and len(parts) >= 2
    return any(
        part in {"job", "opening", "position", "vacancy"} and index + 1 < len(parts)
        for index, part in enumerate(parts)
    ) or ("jobs" in parts and len(parts) > 2 and parts[-1] not in {"search", "category", "locations"})


def _title_company(raw_title: str, url: str) -> tuple[str, str]:
    title = re.sub(r"\s*[|｜]\s*.*$", "", raw_title).strip()
    for separator in (" at ", " - ", " — ", " – ", " @ "):
        if separator.lower() in title.lower():
            pieces = re.split(re.escape(separator), title, maxsplit=1, flags=re.IGNORECASE)
            if len(pieces) == 2 and len(pieces[0]) > 2 and len(pieces[1]) > 1:
                title, company = pieces[0].strip(), pieces[1].strip()
                return _clean_title(title), _clean_company(company)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    segments = [part for part in parsed.path.split("/") if part]
    if "myworkdayjobs.com" in host or "workday.com" in host:
        for index, part in enumerate(segments[:-1]):
            if part.lower() == "job" and index + 2 < len(segments):
                slug = re.sub(r"_[A-Z0-9]{5,}$", "", segments[index + 2], flags=re.IGNORECASE)
                return _clean_title(slug.replace("-", " ")), _clean_company(host.split(".")[0].title())
    if "greenhouse.io" in host and segments:
        company = segments[0]
    elif "lever.co" in host and segments:
        company = segments[0]
    elif "ashbyhq.com" in host and segments:
        company = segments[0]
    else:
        company = host.split(":")[0].split(".")[0]
    return _clean_title(title), _clean_company(company.replace("-", " ").replace("_", " ").title())


def _clean_title(value: str) -> str:
    value = re.sub(r"\b(job|careers?)\s*$", "", value, flags=re.IGNORECASE).strip(" -–—|")
    return value[:500]


def _clean_company(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("|", " ")).strip(" -–—|")[:300]
