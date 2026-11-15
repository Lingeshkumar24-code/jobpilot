"""
Greenhouse job boards — official public board API.

The spec calls for company career portals; Greenhouse publishes each board at
boards-api.greenhouse.io. You supply the board tokens you are authorized to
consume (usually just the company's public careers page token).
"""
from __future__ import annotations

from app.core.config import settings
from app.services.job_sources.base import (
    ConnectorResult,
    JobListing,
    JobSourceConnector,
    clean_text,
    parse_datetime,
)


class GreenhouseConnector(JobSourceConnector):
    key = "greenhouse"
    display_name = "Greenhouse"
    base_url = "https://boards-api.greenhouse.io/v1/boards"
    attribution = "Listings from public Greenhouse job boards. Verify on the employer's site."
    notes = "No credentials required; configure board tokens (GREENHOUSE_BOARDS)."

    def is_configured(self) -> bool:
        return bool(settings.greenhouse_boards)

    def not_configured_reason(self) -> str:
        return (
            "No Greenhouse boards configured. Add board tokens in Settings "
            "(for example the token in boards.greenhouse.io/<token>)."
        )

    async def fetch(self, filters: dict, limit: int, prefs: dict | None = None) -> ConnectorResult:
        result = ConnectorResult(source_key=self.key, display_name=self.display_name)
        boards = (prefs or {}).get("greenhouse_boards") or settings.greenhouse_boards
        if not boards:
            result.skipped_reason = self.not_configured_reason()
            return result

        for board in boards[:10]:
            url = f"{self.base_url}/{board}/jobs"
            try:
                data = await self.get_json(url, params={"content": "true"})
            except Exception as exc:
                result.warnings.append(f"Greenhouse board '{board}' failed: {type(exc).__name__}")
                continue
            jobs = data.get("jobs") if isinstance(data, dict) else None
            if not isinstance(jobs, list):
                result.warnings.append(f"Greenhouse board '{board}' returned an unexpected shape")
                continue
            company = board.replace("-", " ").replace("_", " ").title()
            for item in jobs:
                if not isinstance(item, dict) or not item.get("absolute_url"):
                    continue
                location = None
                if isinstance(item.get("location"), dict):
                    location = item["location"].get("name")
                content = item.get("content") or ""
                listing = JobListing(
                    source_key=self.key,
                    external_id=str(item.get("id") or ""),
                    title=item.get("title") or "",
                    company=company,
                    location=clean_text(location) or None,
                    description=clean_text(content),
                    description_html=content,
                    application_url=item["absolute_url"],
                    source_url=item["absolute_url"],
                    posted_at=parse_datetime(item.get("updated_at") or item.get("first_published")),
                    raw={"board": board, "metadata": item.get("metadata")},
                ).normalize()
                if listing.title:
                    result.listings.append(listing)
                if len(result.listings) >= limit:
                    return result
        return result
