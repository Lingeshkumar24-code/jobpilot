"""
Credentialed sources: LinkedIn, Indeed, Naukri.

These only work through an official partner/API integration that you are
authorized to use. There is deliberately no HTML scraping, no login replay,
no CAPTCHA handling and no anti-bot circumvention anywhere in this file.
If credentials are absent the connector reports that it is not configured
and is skipped — it never fabricates listings.
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


class CredentialedConnector(JobSourceConnector):
    requires_credentials = True
    token_setting: str = ""
    url_setting: str = ""
    token_env_name: str = ""
    url_env_name: str = ""

    def _token(self) -> str | None:
        return getattr(settings, self.token_setting)

    def _url(self) -> str | None:
        return getattr(settings, self.url_setting)

    def is_configured(self) -> bool:
        return bool(self._token() and self._url())

    def not_configured_reason(self) -> str:
        return (
            f"{self.display_name} is disabled: no authorized API access configured. "
            f"Set {self.token_env_name} and {self.url_env_name} with credentials you are "
            "licensed to use. JobPilot does not scrape or bypass access controls."
        )

    async def fetch(self, filters: dict, limit: int, prefs: dict | None = None) -> ConnectorResult:
        result = ConnectorResult(source_key=self.key, display_name=self.display_name)
        if not self.is_configured():
            result.skipped_reason = self.not_configured_reason()
            return result
        headers = {"Authorization": f"Bearer {self._token()}"}
        try:
            data = await self.get_json(self._url(), params={"limit": limit}, headers=headers)
        except Exception as exc:
            result.error = f"{self.display_name} API request failed: {type(exc).__name__}"
            return result

        items = self._extract_items(data)
        if items is None:
            result.error = f"{self.display_name} returned an unexpected response shape"
            return result

        for item in items[:limit]:
            listing = self._to_listing(item)
            if listing:
                result.listings.append(listing)
        return result

    def _extract_items(self, data) -> list | None:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("results", "jobs", "elements", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return None

    def _to_listing(self, item) -> JobListing | None:
        if not isinstance(item, dict):
            return None
        title = item.get("title") or item.get("jobTitle") or item.get("position")
        company = (
            item.get("company")
            or item.get("companyName")
            or (item.get("company") if isinstance(item.get("company"), str) else None)
            or item.get("employer")
        )
        url = item.get("url") or item.get("applyUrl") or item.get("jobUrl") or item.get("apply_url")
        if not (title and company and url):
            return None
        location = item.get("location") or item.get("formattedLocation")
        if isinstance(location, dict):
            location = location.get("name") or location.get("displayName")
        description = item.get("description") or item.get("descriptionHtml") or item.get("snippet")
        return JobListing(
            source_key=self.key,
            external_id=str(item.get("id") or item.get("jobId") or ""),
            title=str(title),
            company=str(company),
            location=clean_text(location) if location else None,
            description=clean_text(description),
            description_html=description if isinstance(description, str) else None,
            application_url=str(url),
            source_url=str(url),
            posted_at=parse_datetime(
                item.get("datePosted") or item.get("postedAt") or item.get("createdAt")
            ),
            raw={"via": "authorized-api"},
        ).normalize()


class LinkedInConnector(CredentialedConnector):
    key = "linkedin"
    display_name = "LinkedIn Jobs"
    base_url = "https://api.linkedin.com"
    attribution = "Listings via LinkedIn's authorized partner API."
    notes = "Requires LinkedIn partner API access. No scraping or session replay."
    token_setting = "LINKEDIN_API_TOKEN"
    url_setting = "LINKEDIN_API_URL"
    token_env_name = "LINKEDIN_API_TOKEN"
    url_env_name = "LINKEDIN_API_URL"


class IndeedConnector(CredentialedConnector):
    key = "indeed"
    display_name = "Indeed"
    base_url = "https://apis.indeed.com"
    attribution = "Listings via Indeed's authorized publisher API."
    notes = "Requires Indeed publisher API access. No scraping."
    token_setting = "INDEED_API_KEY"
    url_setting = "INDEED_API_URL"
    token_env_name = "INDEED_API_KEY"
    url_env_name = "INDEED_API_URL"


class NaukriConnector(CredentialedConnector):
    key = "naukri"
    display_name = "Naukri"
    base_url = "https://www.naukri.com"
    attribution = "Listings via Naukri's authorized partner API."
    notes = "Requires Naukri partner API access. No scraping."
    token_setting = "NAUKRI_API_KEY"
    url_setting = "NAUKRI_API_URL"
    token_env_name = "NAUKRI_API_KEY"
    url_env_name = "NAUKRI_API_URL"
