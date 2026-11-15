from __future__ import annotations

from datetime import datetime

from uuid import UUID
from pydantic import BaseModel, Field


class StructuredFilters(BaseModel):
    role: list[str] = Field(default_factory=list)
    location: list[str] = Field(default_factory=list)
    experience: str | None = None
    minimum_salary: float | None = None
    maximum_salary: float | None = None
    employment_type: list[str] = Field(default_factory=list)
    work_mode: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    posted_within_days: int | None = None
    internship_with_ppo: bool = False
    # Numeric bounds derived from phrases like "fresher" or "2+ years".
    minimum_experience_years: float | None = None
    maximum_experience_years: float | None = None
    notes: list[str] = Field(default_factory=list)


class SearchIntentRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    previous_filters: StructuredFilters | None = None


class SearchIntentResponse(BaseModel):
    query: str
    filters: StructuredFilters
    provider: str
    missing: list[str] = Field(default_factory=list)


class SearchExecuteRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    previous_filters: StructuredFilters | None = None
    sources: list[str] | None = None
    limit: int = Field(default=25, ge=1, le=100)
    save: bool = False
    name: str | None = Field(default=None, max_length=200)


class SearchResultJob(BaseModel):
    id: UUID
    title: str
    company: str
    location: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    work_mode: str | None
    employment_type: str | None
    experience_requirement: str | None
    description: str | None
    application_url: str
    source: str | None
    source_display_name: str | None
    posted_at: datetime | None
    last_verified_at: datetime | None
    is_active: bool
    skills: list[str] = Field(default_factory=list)
    match_score: float | None = None
    match_explanation: dict | None = None


class SearchExecutionResponse(BaseModel):
    query_id: str
    filters: StructuredFilters
    provider: str
    jobs: list[SearchResultJob]
    sources: list[dict]
    warnings: list[str] = Field(default_factory=list)
    total: int


class SearchHistoryItem(BaseModel):
    id: UUID
    raw_text: str
    structured_filters: dict | None
    result_count: int
    is_saved: bool
    last_run_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class SaveSearchRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)



