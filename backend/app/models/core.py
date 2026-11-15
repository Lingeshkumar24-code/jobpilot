"""
SQLAlchemy models for every table in the spec, plus the approval ledger.

Design rules baked in here:
  * UUID primary keys generated application-side (no DB-specific sequence).
  * Soft deletion via ``deleted_at`` where a record must remain auditable.
  * Unique constraints encode the invariants the app relies on: one job per
    normalized identity, one match per (user, job), one application per
    (user, job), one pending approval per application.
  * No candidate data is pre-filled. Empty means empty.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONDoc, TimestampMixin, uuid_pk


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CandidateProfile(Base, TimestampMixin):
    __tablename__ = "candidate_profiles"
    id: Mapped[str] = uuid_pk()
    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    headline: Mapped[str | None] = mapped_column(String(250), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    github_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    portfolio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    experience_level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    total_experience_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    current_company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    expected_salary: Mapped[float | None] = mapped_column(Float, nullable=True)
    skills: Mapped[list | None] = mapped_column(JSONDoc, nullable=True)
    education: Mapped[list | None] = mapped_column(JSONDoc, nullable=True)
    experience: Mapped[list | None] = mapped_column(JSONDoc, nullable=True)
    projects: Mapped[list | None] = mapped_column(JSONDoc, nullable=True)
    certifications: Mapped[list | None] = mapped_column(JSONDoc, nullable=True)
    achievements: Mapped[list | None] = mapped_column(JSONDoc, nullable=True)
    languages: Mapped[list | None] = mapped_column(JSONDoc, nullable=True)
    preferred_roles: Mapped[list | None] = mapped_column(JSONDoc, nullable=True)
    preferred_locations: Mapped[list | None] = mapped_column(JSONDoc, nullable=True)
    preferred_work_modes: Mapped[list | None] = mapped_column(JSONDoc, nullable=True)
    extracted_data: Mapped[dict | None] = mapped_column(JSONDoc, nullable=True)
    # 768-float embedding; stored as JSON so a stock PostgreSQL works, and
    # PGVector can be enabled later without losing data (see docs/aws/08-rds.md).
    profile_embedding: Mapped[list | None] = mapped_column(JSONDoc, nullable=True)
    completeness: Mapped[int] = mapped_column(Integer, default=0)


class ResumeFile(Base, TimestampMixin):
    __tablename__ = "resume_files"
    __table_args__ = (Index("ix_resume_files_user_created", "user_id", "created_at"),)
    id: Mapped[str] = uuid_pk()
    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    s3_key: Mapped[str] = mapped_column(String(1000))
    storage_backend: Mapped[str] = mapped_column(String(20), default="local")  # s3 | local
    original_filename: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(10))  # pdf | docx
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class ResumeVersion(Base, TimestampMixin):
    __tablename__ = "resume_versions"
    __table_args__ = (
        UniqueConstraint("resume_file_id", "version_number", name="uq_resume_version_number"),
        Index("ix_resume_versions_user", "user_id"),
    )
    id: Mapped[str] = uuid_pk()
    resume_file_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("resume_files.id", ondelete="CASCADE")
    )
    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    parsed_json: Mapped[dict | None] = mapped_column(JSONDoc, nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(40), default="heuristic")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class SearchQuery(Base, TimestampMixin):
    __tablename__ = "search_queries"
    __table_args__ = (Index("ix_search_queries_user_created", "user_id", "created_at"),)
    id: Mapped[str] = uuid_pk()
    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text)
    structured_filters: Mapped[dict | None] = mapped_column(JSONDoc, nullable=True)
    intent_provider: Mapped[str] = mapped_column(String(40), default="rule_based")
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    is_saved: Mapped[bool] = mapped_column(Boolean, default=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobSource(Base, TimestampMixin):
    __tablename__ = "job_sources"
    id: Mapped[str] = uuid_pk()
    name: Mapped[str] = mapped_column(String(100), unique=True)
    connector_key: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    attribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_credentials: Mapped[bool] = mapped_column(Boolean, default=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_jobs_dedup_key"),
        Index("ix_jobs_posted_at", "posted_at"),
        Index("ix_jobs_company_title", "company", "title"),
    )
    id: Mapped[str] = uuid_pk()
    source_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("job_sources.id"), index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    company: Mapped[str] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    work_mode: Mapped[str | None] = mapped_column(String(30), nullable=True)
    experience_requirement: Mapped[str | None] = mapped_column(String(200), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    application_url: Mapped[str] = mapped_column(String(2000))
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    posted_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    dedup_key: Mapped[str] = mapped_column(String(64))
    description_embedding: Mapped[list | None] = mapped_column(JSONDoc, nullable=True)
    duplicate_sources: Mapped[list | None] = mapped_column(JSONDoc, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONDoc, nullable=True)


class JobSkill(Base, TimestampMixin):
    __tablename__ = "job_skills"
    __table_args__ = (UniqueConstraint("job_id", "normalized_skill", name="uq_job_skill"),)
    id: Mapped[str] = uuid_pk()
    job_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    skill: Mapped[str] = mapped_column(String(100))
    normalized_skill: Mapped[str] = mapped_column(String(100))


class JobMatch(Base, TimestampMixin):
    __tablename__ = "job_matches"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_job_match_user_job"),)
    id: Mapped[str] = uuid_pk()
    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    match_score: Mapped[float] = mapped_column(Float)
    match_explanation: Mapped[dict | None] = mapped_column(JSONDoc, nullable=True)
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False)


class Application(Base, TimestampMixin):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_applications_dedupe"),
        Index("ix_applications_user_status", "user_id", "status"),
    )
    id: Mapped[str] = uuid_pk()
    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    job_id: Mapped[str] = mapped_column(Uuid(as_uuid=True), ForeignKey("jobs.id"))
    resume_version_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("resume_versions.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(40), default="DISCOVERED")
    dedupe_key: Mapped[str] = mapped_column(String(80))
    preview: Mapped[dict | None] = mapped_column(JSONDoc, nullable=True)
    screenshot_s3_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    confirmation_evidence: Mapped[dict | None] = mapped_column(JSONDoc, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submission_attempts: Mapped[int] = mapped_column(Integer, default=0)


class ApplicationAnswer(Base, TimestampMixin):
    __tablename__ = "application_answers"
    __table_args__ = (UniqueConstraint("application_id", "field_name", name="uq_answer_field"),)
    id: Mapped[str] = uuid_pk()
    application_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    field_name: Mapped[str] = mapped_column(String(200))
    field_label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    field_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    field_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="profile")  # profile|resume|user|ai
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_user_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ApplicationEvent(Base, TimestampMixin):
    __tablename__ = "application_events"
    id: Mapped[str] = uuid_pk()
    application_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(60))
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actor: Mapped[str] = mapped_column(String(60), default="system")  # user|system|browser|agent
    payload: Mapped[dict | None] = mapped_column(JSONDoc, nullable=True)


class Approval(Base, TimestampMixin):
    """One-time, application-specific approval ledger."""

    __tablename__ = "approvals"
    id: Mapped[str] = uuid_pk()
    application_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), unique=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    approved_by: Mapped[str] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONDoc, nullable=True)


class BrowserSession(Base, TimestampMixin):
    __tablename__ = "browser_sessions"
    id: Mapped[str] = uuid_pk()
    application_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    worker_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    session_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="STARTED")
    last_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    screenshot_s3_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONDoc, nullable=True)


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_user_created", "user_id", "created_at"),)
    id: Mapped[str] = uuid_pk()
    user_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    thread_id: Mapped[str] = mapped_column(String(80), unique=True)
    goal: Mapped[str] = mapped_column(Text, default="")
    agent_name: Mapped[str] = mapped_column(String(80), default="jobpilot_graph")
    status: Mapped[str] = mapped_column(String(40), default="running")
    current_node: Mapped[str | None] = mapped_column(String(80), nullable=True)
    state: Mapped[dict | None] = mapped_column(JSONDoc, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONDoc, nullable=True)
    interrupt_payload: Mapped[dict | None] = mapped_column(JSONDoc, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AutomationWorkflow(Base, TimestampMixin):
    __tablename__ = "automation_workflows"
    id: Mapped[str] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), unique=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    n8n_workflow_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(40), nullable=True)


class UserPreference(Base, TimestampMixin):
    __tablename__ = "user_preferences"
    id: Mapped[str] = uuid_pk()
    user_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    preferences: Mapped[dict | None] = mapped_column(JSONDoc, nullable=True)
    digest_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    digest_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # HH:MM
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    greenhouse_boards: Mapped[list | None] = mapped_column(JSONDoc, nullable=True)
    lever_sites: Mapped[list | None] = mapped_column(JSONDoc, nullable=True)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_user_created", "user_id", "created_at"),)
    id: Mapped[str] = uuid_pk()
    user_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONDoc, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
