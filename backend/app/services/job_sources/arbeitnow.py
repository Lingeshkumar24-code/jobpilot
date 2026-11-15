"""Arbeitnow public job-board API. https://www.arbeitnow.com/api/job-board-api"""
from __future__ import annotations

from app.services.job_sources.base import (
    ConnectorResult,
    JobListing,
    JobSourceConnector,
    clean_text,
    parse_datetime,
)


class ArbeitnowConnector(JobSourceConnector):
    key = "arbeitnow"
    display_name = "Arbeitnow"
    base_url = "https://www.arbeitnow.com/api/job-board-api"
    attribution = "Listings from Arbeitnow (arbeitnow.com). Verify details on the source page."
    notes = "Public JSON feed. No authentication."

    async def fetch(self, filters: dict, limit: int, prefs: dict | None = None) -> ConnectorResult:
        result = ConnectorResult(source_key=self.key, display_name=self.display_name)
        data = await self.get_json(self.base_url)
        jobs = data.get("data") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            result.error = "Unexpected response shape from Arbeitnow"
            return result

        for item in jobs[: limit * 3]:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not url:
                continue
            remote = bool(item.get("remote"))
            job_types = item.get("job_types") or []
            listing = JobListing(
                source_key=self.key,
                external_id=item.get("slug") or item.get("url"),
                title=item.get("title") or "",
                company=item.get("company_name") or "",
                location=item.get("location") or ("Remote" if remote else None),
                description=clean_text(item.get("description")),
                description_html=item.get("description"),
                application_url=url,
                source_url=url,
                work_mode="remote" if remote else None,
                employment_type=_employment_type(job_types),
                posted_at=parse_datetime(item.get("created_at")),
                raw={"tags": item.get("tags", []), "job_types": job_types},
            ).normalize()
            if listing.title and listing.company:
                result.listings.append(listing)
            if len(result.listings) >= limit:
                break
        return result


def _employment_type(job_types: list) -> str | None:
    joined = " ".join(str(j) for j in job_types).lower()
    if "intern" in joined:
        return "internship"
    if "part" in joined:
        return "part_time"
    if "contract" in joined or "freelance" in joined:
        return "contract"
    if "full" in joined or "permanent" in joined:
        return "full_time"
    return None
