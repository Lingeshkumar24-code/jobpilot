"""User preferences, safety-visible system status, and the personal audit trail."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.core import (
    Application,
    AuditLog,
    CandidateProfile,
    Job,
    JobMatch,
    JobSource,
    ResumeFile,
    User,
    UserPreference,
)
from app.schemas.system import AuditEntry, PreferenceOut, PreferenceUpdate, SystemStatus
from app.services.browser_client import browser_client
from app.services.discovery import ensure_sources
from app.services.job_sources import source_metadata
from app.services.storage import storage

router = APIRouter()


async def _prefs(db: AsyncSession, user: User) -> UserPreference:
    row = (
        await db.execute(select(UserPreference).where(UserPreference.user_id == user.id))
    ).scalar_one_or_none()
    if row is None:
        row = UserPreference(user_id=user.id, preferences={})
        db.add(row)
        await db.flush()
    return row


@router.get("/preferences", response_model=PreferenceOut)
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _prefs(db, current_user)
    await db.commit()
    return PreferenceOut.model_validate(row)


@router.put("/preferences", response_model=PreferenceOut)
async def update_preferences(
    payload: PreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _prefs(db, current_user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    await db.commit()
    await db.refresh(row)
    return PreferenceOut.model_validate(row)


@router.get("/system", response_model=SystemStatus)
async def system_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    database = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        database = "error"

    await ensure_sources(db)
    await db.commit()
    source_rows = (
        await db.execute(
            select(JobSource.connector_key, func.count(Job.id))
            .join(Job, Job.source_id == JobSource.id)
            .where(Job.is_active.is_(True))
            .group_by(JobSource.connector_key)
        )
    ).all()
    jobs_by_source = {row[0]: row[1] for row in source_rows}
    sources = []
    for meta in source_metadata():
        sources.append(
            {
                "key": meta["key"],
                "display_name": meta["display_name"],
                "configured": meta["configured"],
                "requires_credentials": meta["requires_credentials"],
                "jobs_stored": jobs_by_source.get(meta["key"], 0),
                "notes": meta["notes"],
            }
        )

    counts = {
        "jobs": (
            await db.execute(select(func.count(Job.id)).where(Job.is_active.is_(True)))
        ).scalar_one(),
        "matches": (
            await db.execute(
                select(func.count(JobMatch.id)).where(JobMatch.user_id == current_user.id)
            )
        ).scalar_one(),
        "applications": (
            await db.execute(
                select(func.count(Application.id)).where(
                    Application.user_id == current_user.id, Application.deleted_at.is_(None)
                )
            )
        ).scalar_one(),
        "pending_approvals": (
            await db.execute(
                select(func.count(Application.id)).where(
                    Application.user_id == current_user.id,
                    Application.status.in_(["USER_APPROVAL_PENDING", "APPROVED"]),
                )
            )
        ).scalar_one(),
        "resumes": (
            await db.execute(
                select(func.count(ResumeFile.id)).where(
                    ResumeFile.user_id == current_user.id, ResumeFile.deleted_at.is_(None)
                )
            )
        ).scalar_one(),
    }
    profile = (
        await db.execute(select(CandidateProfile).where(CandidateProfile.user_id == current_user.id))
    ).scalar_one_or_none()
    if profile is not None:
        counts["profile_completeness"] = profile.completeness

    worker = await browser_client.health()
    provider = "openrouter" if settings.OPENROUTER_API_KEY else "gemini" if settings.GEMINI_API_KEY else "ollama" if settings.OLLAMA_BASE_URL else "rule_based"
    return SystemStatus(
        environment=settings.ENVIRONMENT,
        database=database,
        storage_backend=storage.backend,
        llm_provider=provider,
        browser_worker_configured=bool(browser_client.configured),
        browser_worker_reachable=worker.get("reachable"),
        n8n_configured=bool(settings.N8N_WEBHOOK_BASE_URL),
        sources=sources,
        counts=counts,
        checked_at=datetime.now(timezone.utc),
    )


@router.get("/audit", response_model=list[AuditEntry])
async def audit_trail(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.user_id == current_user.id)
            .order_by(AuditLog.created_at.desc())
            .limit(min(max(limit, 1), 200))
        )
    ).scalars().all()
    return [
        AuditEntry(
            id=str(row.id),
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            details=row.details,
            ip_address=row.ip_address,
            created_at=row.created_at,
        )
        for row in rows
    ]
