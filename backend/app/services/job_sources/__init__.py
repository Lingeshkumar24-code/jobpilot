"""Connector registry. One instance per source, no hidden shared state."""
from __future__ import annotations

from app.services.job_sources.arbeitnow import ArbeitnowConnector
from app.services.job_sources.base import (
    ConnectorResult,
    JobListing,
    JobSourceConnector,
    clean_text,
    parse_datetime,
    parse_salary_range,
)
from app.services.job_sources.credentialed import (
    IndeedConnector,
    LinkedInConnector,
    NaukriConnector,
)
from app.services.job_sources.firecrawl import FirecrawlConnector
from app.services.job_sources.greenhouse import GreenhouseConnector
from app.services.job_sources.lever import LeverConnector
from app.services.job_sources.remoteok import RemoteOKConnector
from app.services.job_sources.remotive import RemotiveConnector

CONNECTORS: dict[str, JobSourceConnector] = {
    connector.key: connector
    for connector in (
        RemoteOKConnector(),
        ArbeitnowConnector(),
        RemotiveConnector(),
        FirecrawlConnector(),
        GreenhouseConnector(),
        LeverConnector(),
        LinkedInConnector(),
        IndeedConnector(),
        NaukriConnector(),
    )
}

SOURCE_ORDER = list(CONNECTORS)


def get_connector(key: str) -> JobSourceConnector | None:
    return CONNECTORS.get(key)


def source_metadata() -> list[dict]:
    return [
        {
            "key": c.key,
            "name": c.key,
            "display_name": c.display_name,
            "base_url": c.base_url,
            "attribution": c.attribution,
            "requires_credentials": c.requires_credentials,
            "configured": c.is_configured(),
            "notes": c.notes,
            "reason": c.not_configured_reason() if not c.is_configured() else None,
        }
        for c in CONNECTORS.values()
    ]


__all__ = [
    "CONNECTORS",
    "SOURCE_ORDER",
    "ConnectorResult",
    "JobListing",
    "JobSourceConnector",
    "clean_text",
    "get_connector",
    "parse_datetime",
    "parse_salary_range",
    "source_metadata",
]
