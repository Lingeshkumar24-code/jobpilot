"""Remotive public remote-jobs API. https://remotive.com/api/remote-jobs"""
from __future__ import annotations

from app.services.job_sources.base import (
    ConnectorResult,
    JobListing,
    JobSourceConnector,
    clean_text,
    parse_datetime,
    parse_salary_range,
)


class RemotiveConnector(JobSourceConnector):
    key = "remotive"
    display_name = "Remotive"
    base_url = "https://remotive.com/api/remote-jobs"
    attribution = "Listings from Remotive (remotive.com). Verify details on the source page."
    notes = "Public JSON feed. Remote-only roles."

    async def fetch(self, filters: dict, limit: int, prefs: dict | None = None) -> ConnectorResult:
        result = ConnectorResult(source_key=self.key, display_name=self.display_name)
        data = await self.get_json(self.base_url, params={"limit": min(limit * 3, 150)})
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            result.error = "Unexpected response shape from Remotive"
            return result

        for item in jobs:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            salary_min, salary_max, currency = parse_salary_range(item.get("salary"))
            listing = JobListing(
                source_key=self.key,
                external_id=str(item.get("id") or item.get("url")),
                title=item.get("title") or "",
                company=item.get("company_name") or "",
                location=item.get("candidate_required_location") or "Remote",
                description=clean_text(item.get("description")),
                description_html=item.get("description"),
                application_url=item["url"],
                source_url=item["url"],
                salary_min=salary_min,
                salary_max=salary_max,
                salary_currency=currency,
                work_mode="remote",
                employment_type=_employment_type(item.get("job_type")),
                posted_at=parse_datetime(item.get("publication_date")),
                raw={"tags": item.get("tags", []), "category": item.get("category")},
            ).normalize()
            if listing.title and listing.company:
                result.listings.append(listing)
            if len(result.listings) >= limit:
                break
        return result


def _employment_type(value: str | None) -> str | None:
    low = (value or "").lower()
    if "intern" in low:
        return "internship"
    if "part" in low:
        return "part_time"
    if "contract" in low:
        return "contract"
    if "full" in low:
        return "full_time"
    return None
