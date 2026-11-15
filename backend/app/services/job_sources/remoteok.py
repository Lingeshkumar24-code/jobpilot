"""Remote OK public job feed. https://remoteok.com/api — attribution required."""
from __future__ import annotations

from app.services.job_sources.base import (
    ConnectorResult,
    JobListing,
    JobSourceConnector,
    clean_text,
    parse_datetime,
    parse_salary_range,
)


class RemoteOKConnector(JobSourceConnector):
    key = "remoteok"
    display_name = "Remote OK"
    base_url = "https://remoteok.com/api"
    attribution = "Listings from Remote OK (remoteok.com). Verify details on the source page."
    notes = "Public JSON feed. No authentication. Remote-only roles."

    async def fetch(self, filters: dict, limit: int, prefs: dict | None = None) -> ConnectorResult:
        result = ConnectorResult(source_key=self.key, display_name=self.display_name)
        data = await self.get_json(self.base_url)
        if not isinstance(data, list):
            result.error = "Unexpected response shape from Remote OK"
            return result

        for item in data[: limit * 3]:
            if not isinstance(item, dict) or "position" not in item:
                continue
            url = item.get("url") or item.get("apply_url")
            if not url:
                continue
            salary_min, salary_max, currency = parse_salary_range(
                item.get("salary_min") or item.get("salary_max")
            )
            description = clean_text(item.get("description"))
            listing = JobListing(
                source_key=self.key,
                external_id=str(item.get("id") or item.get("slug") or ""),
                title=item.get("position") or "",
                company=item.get("company") or "",
                location=item.get("location") or "Remote",
                description=description,
                description_html=item.get("description"),
                application_url=url,
                source_url=url,
                salary_min=salary_min,
                salary_max=salary_max,
                salary_currency=currency,
                work_mode="remote",
                employment_type=_employment_type(item.get("position", "")),
                posted_at=parse_datetime(item.get("date") or item.get("epoch")),
                raw={"tags": item.get("tags", [])},
            ).normalize()
            if listing.title and listing.company:
                result.listings.append(listing)
            if len(result.listings) >= limit:
                break
        return result


def _employment_type(title: str) -> str | None:
    low = title.lower()
    if "intern" in low:
        return "internship"
    if "contract" in low:
        return "contract"
    if "part-time" in low or "part time" in low:
        return "part_time"
    if "full" in low:
        return "full_time"
    return None
