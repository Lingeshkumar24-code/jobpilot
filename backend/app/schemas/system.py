from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AgentRunRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=1000)
    prepare_applications: bool = False
    limit: int = Field(default=5, ge=1, le=20)


class AgentResumeRequest(BaseModel):
    approved: bool
    application_id: str | None = None
    proof: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=1000)


class AgentStep(BaseModel):
    node: str
    label: str
    status: str
    detail: str | None = None
    at: str


class AgentRunOut(BaseModel):
    id: UUID
    thread_id: str
    goal: str
    status: str
    current_node: str | None = None
    state: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    interrupt_payload: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    steps: list[AgentStep] = Field(default_factory=list)


class AgentRunList(BaseModel):
    runs: list[AgentRunOut]
    total: int


class WorkflowOut(BaseModel):
    id: UUID
    name: str
    key: str
    description: str | None = None
    is_active: bool
    last_run_at: datetime | None = None
    last_status: str | None = None


class WebhookResponse(BaseModel):
    accepted: bool
    run_id: str | None = None
    message: str


class PreferenceOut(BaseModel):
    digest_enabled: bool = False
    digest_time: str | None = None
    email_notifications: bool = True
    greenhouse_boards: list[str] | None = None
    lever_sites: list[str] | None = None
    preferences: dict[str, Any] | None = None


class PreferenceUpdate(BaseModel):
    digest_enabled: bool | None = None
    digest_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    email_notifications: bool | None = None
    greenhouse_boards: list[str] | None = None
    lever_sites: list[str] | None = None
    preferences: dict[str, Any] | None = None


class AuditEntry(BaseModel):
    id: UUID
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    details: dict[str, Any] | None = None
    ip_address: str | None = None
    created_at: datetime


class SystemStatus(BaseModel):
    environment: str
    database: str
    storage_backend: str
    llm_provider: str
    browser_worker_configured: bool
    browser_worker_reachable: bool | None = None
    n8n_configured: bool
    sources: list[dict[str, Any]]
    counts: dict[str, int]
    checked_at: datetime


