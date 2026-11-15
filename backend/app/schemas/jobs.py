from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class JobOut(BaseModel):
    id: UUID
    title: str
    company: str
    location: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    work_mode: str | None = None
    employment_type: str | None = None
    experience_requirement: str | None = None
    description: str | None = None
    application_url: str
    source_url: str | None = None
    source: str | None = None
    source_display_name: str | None = None
    posted_at: datetime | None = None
    last_verified_at: datetime | None = None
    is_active: bool = True
    skills: list[str] = Field(default_factory=list)
    match_score: float | None = None
    match_explanation: dict[str, Any] | None = None


class JobListResponse(BaseModel):
    jobs: list[JobOut]
    total: int
    limit: int
    offset: int


class JobDetailResponse(BaseModel):
    job: JobOut
    source_attribution: str | None = None
    duplicates: list[dict[str, Any]] = Field(default_factory=list)


class SourceOut(BaseModel):
    key: str
    display_name: str
    base_url: str | None = None
    attribution: str | None = None
    requires_credentials: bool
    is_enabled: bool
    configured: bool
    last_synced_at: datetime | None = None
    last_sync_error: str | None = None
    notes: str | None = None


class MatchOut(BaseModel):
    id: UUID
    job: JobOut
    match_score: float
    match_explanation: dict[str, Any] | None = None
    is_dismissed: bool
    created_at: datetime


class MatchListResponse(BaseModel):
    matches: list[MatchOut]
    total: int


class MatchStats(BaseModel):
    total: int
    dismissed: int
    scored_today: int
    average_score: float | None = None
    above_threshold: int = 0


