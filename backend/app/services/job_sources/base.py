"""Shared types and HTTP plumbing for job-source connectors."""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.services.skills import extract_skills

logger = logging.getLogger(__name__)


@dataclass
class JobListing:
    source_key: str
    external_id: str | None
    title: str
    company: str
    application_url: str
    location: str | None = None
    description: str | None = None
    description_html: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    work_mode: str | None = None
    employment_type: str | None = None
    experience_requirement: str | None = None
    posted_at: datetime | None = None
    source_url: str | None = None
    skills: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def normalize(self) -> "JobListing":
        self.title = clean_text(self.title)[:500]
        self.company = clean_text(self.company)[:300]
        if self.location:
            self.location = clean_text(self.location)[:300]
        if self.description:
            self.description = self.description[:50000]
        if not self.skills:
            self.skills = extract_skills(f"{self.title} {self.description or ''}")
        self.application_url = self.application_url.strip()
        self.source_url = self.source_url or self.application_url
        return self


@dataclass
class ConnectorResult:
    source_key: str
    display_name: str
    listings: list[JobListing] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    skipped_reason: str | None = None
    duration_ms: int | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.skipped_reason is None


class JobSourceConnector:
    key: str = ""
    display_name: str = ""
    attribution: str = ""
    base_url: str = ""
    requires_credentials: bool = False
    notes: str = ""

    def is_configured(self) -> bool:
        return True

    def not_configured_reason(self) -> str:
        return ""

    async def fetch(self, filters: dict, limit: int, prefs: dict | None = None) -> ConnectorResult:
        raise NotImplementedError

    # -- helpers -----------------------------------------------------------

    async def get_json(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> Any:
        timeout = httpx.Timeout(settings.JOB_HTTP_TIMEOUT_SECONDS)
        request_headers = {
            "User-Agent": settings.JOB_USER_AGENT,
            "Accept": "application/json",
        }
        if headers:
            request_headers.update(headers)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, params=params, headers=request_headers)
            response.raise_for_status()
            return response.json()


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<br\s*/?>|</p>|</li>|</div>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            # Heuristic: seconds vs milliseconds.
            seconds = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return parse_datetime(int(text))
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%b %d, %Y", "%Y/%m/%d"):
                try:
                    return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
    return None


def parse_salary_range(value: Any) -> tuple[float | None, float | None, str | None]:
    """Best-effort parsing of source-provided salary text. Never invents one."""
    if value is None:
        return None, None, None
    if isinstance(value, dict):
        minimum = value.get("min") or value.get("minimum")
        maximum = value.get("max") or value.get("maximum")
        currency = value.get("currency")
        try:
            return (
                float(minimum) if minimum is not None else None,
                float(maximum) if maximum is not None else None,
                str(currency)[:10] if currency else None,
            )
        except (TypeError, ValueError):
            return None, None, None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None, None, None
        numbers = re.findall(r"\d[\d,]*(?:\.\d+)?", text)
        values: list[float] = []
        for number in numbers[:2]:
            try:
                values.append(float(number.replace(",", "")))
            except ValueError:
                continue
        currency = None
        if re.search(r"₹|inr|rs\.?", text, re.IGNORECASE):
            currency = "INR"
        elif re.search(r"€|eur", text, re.IGNORECASE):
            currency = "EUR"
        elif re.search(r"\$|usd", text, re.IGNORECASE):
            currency = "USD"
        elif re.search(r"£|gbp", text, re.IGNORECASE):
            currency = "GBP"
        if not values:
            return None, None, currency
        if len(values) == 1:
            return values[0], values[0], currency
        return min(values), max(values), currency
    return None, None, None
