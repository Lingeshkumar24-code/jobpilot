"""Lever postings API. https://api.lever.co/v0/postings/<site>?mode=json"""
from __future__ import annotations

from app.core.config import settings
from app.services.job_sources.base import (
    ConnectorResult,
    JobListing,
    JobSourceConnector,
    clean_text,
    parse_datetime,
    parse_salary_range,
)


class LeverConnector(JobSourceConnector):
    key = "lever"
    display_name = "Lever"
    base_url = "https://api.lever.co/v0/postings"
    attribution = "Listings from public Lever job boards. Verify on the employer's site."
    notes = "No credentials required; configure site tokens (LEVER_SITES)."

    def is_configured(self) -> bool:
        return bool(settings.lever_sites)

    def not_configured_reason(self) -> str:
        return "No Lever sites configured. Add site tokens in Settings (jobs.lever.co/<site>)."

    async def fetch(self, filters: dict, limit: int, prefs: dict | None = None) -> ConnectorResult:
        result = ConnectorResult(source_key=self.key, display_name=self.display_name)
        sites = (prefs or {}).get("lever_sites") or settings.lever_sites
        if not sites:
            result.skipped_reason = self.not_configured_reason()
            return result

        for site in sites[:10]:
            url = f"{self.base_url}/{site}"
            try:
                data = await self.get_json(url, params={"mode": "json"})
            except Exception as exc:
                result.warnings.append(f"Lever site '{site}' failed: {type(exc).__name__}")
                continue
            if not isinstance(data, list):
                result.warnings.append(f"Lever site '{site}' returned an unexpected shape")
                continue
            company = site.replace("-", " ").replace("_", " ").title()
            for item in data:
                if not isinstance(item, dict) or not item.get("hostedUrl"):
                    continue
                categories = item.get("categories") or {}
                salary_min, salary_max, currency = (None, None, None)
                if isinstance(item.get("salaryRange"), dict):
                    salary_min, salary_max, currency = parse_salary_range(item["salaryRange"])
                location = categories.get("location") or None
                work_mode = "remote" if location and "remote" in str(location).lower() else None
                listing = JobListing(
                    source_key=self.key,
                    external_id=str(item.get("id") or ""),
                    title=item.get("text") or "",
                    company=company,
                    location=location,
                    description=clean_text(item.get("descriptionPlain") or item.get("description")),
                    description_html=item.get("description"),
                    application_url=item["hostedUrl"],
                    source_url=item["hostedUrl"],
                    salary_min=salary_min,
                    salary_max=salary_max,
                    salary_currency=currency,
                    work_mode=work_mode,
                    employment_type=_employment_type(categories.get("commitment")),
                    posted_at=parse_datetime(item.get("createdAt")),
                    raw={"categories": categories},
                ).normalize()
                if listing.title:
                    result.listings.append(listing)
                if len(result.listings) >= limit:
                    return result
        return result


def _employment_type(value: str | None) -> str | None:
    low = (value or "").lower()
    if "intern" in low:
        return "internship"
    if "part" in low:
        return "part_time"
    if "contract" in low or "temporary" in low:
        return "contract"
    if "full" in low:
        return "full_time"
    return None
