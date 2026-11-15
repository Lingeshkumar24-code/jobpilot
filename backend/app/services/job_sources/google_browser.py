"""Google job discovery performed by the isolated Playwright browser worker."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from app.services.browser_client import BrowserClient, BrowserWorkerError, browser_client
from app.services.job_sources.base import ConnectorResult, JobListing, JobSourceConnector


class GoogleBrowserConnector(JobSourceConnector):
    key = "google_browser"
    display_name = "Google (Playwright browser)"
    base_url = "https://www.google.com"
    attribution = "Public web results discovered through Google in the JobPilot browser. Verify each posting on the employer site."
    requires_credentials = False
    notes = "Searches Google in the isolated Playwright Chromium worker. Google may require a manual CAPTCHA check."

    def __init__(self, client: BrowserClient | None = None) -> None:
        self.client = client or browser_client

    def is_configured(self) -> bool:
        return self.client.configured

    def not_configured_reason(self) -> str:
        return "The Playwright browser worker is not configured."

    async def fetch(self, filters: dict, limit: int, prefs: dict | None = None) -> ConnectorResult:
        result = ConnectorResult(source_key=self.key, display_name=self.display_name)
        if not self.is_configured():
            result.skipped_reason = self.not_configured_reason()
            return result

        role = " ".join(str(value).strip() for value in filters.get("role") or [] if str(value).strip())
        location = " ".join(str(value).strip() for value in filters.get("location") or [] if str(value).strip())
        terms = [role or "jobs"]
        if location:
            terms.append(location)
        terms.extend(("job opening", "careers", "apply"))
        if filters.get("work_mode") and "remote" in filters["work_mode"]:
            terms.append("remote")
        try:
            response = await self.client.google_search(" ".join(terms), min(limit, 50))
        except BrowserWorkerError as exc:
            result.error = str(exc)
            return result

        for index, hit in enumerate(response.get("results") or []):
            if not isinstance(hit, dict):
                continue
            url = hit.get("url")
            title = _clean(hit.get("title"))
            if not title or not _is_job_result(url, title, hit.get("snippet", "")):
                continue
            parsed = urlparse(url)
            host = (parsed.hostname or "employer").removeprefix("www.")
            company = _company_from_title(title) or host.split(":")[0].split(".")[0].replace("-", " ").title()
            result.listings.append(
                JobListing(
                    source_key=self.key,
                    external_id=url,
                    title=_job_title(title),
                    company=company,
                    location=location or None,
                    description=_clean(hit.get("snippet")) or None,
                    application_url=url,
                    source_url=url,
                    raw={"google_rank": index + 1, "google_query": response.get("query")},
                ).normalize()
            )
            if len(result.listings) >= limit:
                break
        if not result.listings:
            result.warnings.append("Google returned no results that looked like individual job postings.")
        return result


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_job_result(url: object, title: str, snippet: str) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    path = parsed.path.lower().rstrip("/")
    if any(blocked in host for blocked in ("google.", "youtube.com", "facebook.com", "linkedin.com/jobs/search")):
        return False
    if any(token in path for token in ("/search", "/jobs-in-", "/job-search", "/category/", "/tag/")):
        return False
    if path in {"", "/", "/jobs", "/careers", "/career", "/open-positions"}:
        return False
    evidence = f"{title} {snippet}".lower()
    if not re.search(r"\b(job|jobs|career|careers|engineer|developer|analyst|scientist|intern|manager|designer|specialist|architect|consultant|opening|vacancy|apply)\b", evidence):
        return False
    return True


def _company_from_title(title: str) -> str | None:
    for separator in (" | ", " — ", " – ", " - ", " at "):
        if separator.lower() in title.lower():
            parts = re.split(re.escape(separator), title, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2 and parts[1].strip():
                value = re.sub(r"\b(careers?|jobs?)\b.*$", "", parts[1], flags=re.IGNORECASE).strip(" -|–—")
                if 1 < len(value) < 100:
                    return value
    return None


def _job_title(title: str) -> str:
    value = re.split(r"\s*[|｜]\s*", title, maxsplit=1)[0]
    value = re.sub(r"\s*[-–—]\s*(careers?|jobs?)\b.*$", "", value, flags=re.IGNORECASE)
    return value.strip(" -–—|")[:500]
