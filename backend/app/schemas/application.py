from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CreateApplicationRequest(BaseModel):
    job_id: str
    resume_version_id: str | None = None


class AnswerOut(BaseModel):
    id: UUID
    field_name: str
    field_label: str | None = None
    field_type: str | None = None
    field_value: str | None = None
    source: str
    confidence: float | None = None
    is_required: bool
    is_user_edited: bool
    validation_error: str | None = None

    class Config:
        from_attributes = True


class EventOut(BaseModel):
    id: UUID
    event_type: str
    from_status: str | None = None
    to_status: str | None = None
    actor: str
    payload: dict[str, Any] | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ApplicationOut(BaseModel):
    id: UUID
    job: dict[str, Any]
    status: str
    resume_version_id: str | None = None
    preview: dict[str, Any] | None = None
    failure_reason: str | None = None
    outcome: str | None = None
    approved_at: datetime | None = None
    submitted_at: datetime | None = None
    confirmed_at: datetime | None = None
    submission_attempts: int = 0
    screenshot_available: bool = False
    approval_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ApplicationDetail(ApplicationOut):
    answers: list[AnswerOut] = Field(default_factory=list)
    events: list[EventOut] = Field(default_factory=list)
    confirmation_evidence: dict[str, Any] | None = None
    browser_session: dict[str, Any] | None = None


class ApplicationListResponse(BaseModel):
    applications: list[ApplicationOut]
    total: int
    counts: dict[str, int] = Field(default_factory=dict)


class AnswerUpdate(BaseModel):
    field_value: str = Field(max_length=10000)


class ApprovalRequestOut(BaseModel):
    application_id: str
    approval_token: str
    expires_at: datetime
    summary: dict[str, Any]


class ApproveRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class ApproveResponse(BaseModel):
    application: ApplicationOut
    proof: dict[str, Any]


class SubmitRequest(BaseModel):
    proof: dict[str, Any]


class SubmitResponse(BaseModel):
    application: ApplicationOut
    outcome: str | None = None
    evidence: dict[str, Any] | None = None
    validation_errors: list[str] = Field(default_factory=list)


class RejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class ManualConfirmRequest(BaseModel):
    evidence: str = Field(min_length=5, max_length=2000)


class OutcomeRequest(BaseModel):
    outcome: str
    note: str | None = Field(default=None, max_length=1000)


class ApplicationStats(BaseModel):
    total: int
    by_status: dict[str, int]
    confirmed: int
    needs_input: int
    pending_approval: int
    interviews: int
    offers: int


