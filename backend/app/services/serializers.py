"""Shared response builders (kept in one place so every endpoint agrees)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Application, ApplicationAnswer, ApplicationEvent, BrowserSession, Job, JobMatch, JobSkill, JobSource
from app.schemas.application import AnswerOut, ApplicationDetail, ApplicationOut, EventOut
from app.schemas.jobs import JobOut, MatchOut


async def sources_by_id(db: AsyncSession) -> dict:
    rows = (await db.execute(select(JobSource))).scalars().all()
    return {row.id: row for row in rows}


async def skills_by_job(db: AsyncSession, job_ids: list) -> dict:
    if not job_ids:
        return {}
    rows = (await db.execute(select(JobSkill).where(JobSkill.job_id.in_(job_ids)))).scalars().all()
    result: dict = {}
    for row in rows:
        result.setdefault(row.job_id, []).append(row.skill)
    return result


async def matches_by_job(db: AsyncSession, user_id, job_ids: list) -> dict:
    if not job_ids:
        return {}
    rows = (
        await db.execute(
            select(JobMatch).where(JobMatch.user_id == user_id, JobMatch.job_id.in_(job_ids))
        )
    ).scalars().all()
    return {row.job_id: row for row in rows}


def job_out(job: Job, source: JobSource | None, skills: list[str], match: JobMatch | None = None) -> JobOut:
    return JobOut(
        id=str(job.id),
        title=job.title,
        company=job.company,
        location=job.location,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_currency=job.salary_currency,
        work_mode=job.work_mode,
        employment_type=job.employment_type,
        experience_requirement=job.experience_requirement,
        description=job.description,
        application_url=job.application_url,
        source_url=job.source_url,
        source=source.connector_key if source else None,
        source_display_name=source.display_name if source else None,
        posted_at=job.posted_at,
        last_verified_at=job.last_verified_at,
        is_active=job.is_active,
        skills=skills,
        match_score=match.match_score if match else None,
        match_explanation=match.match_explanation if match else None,
    )


async def jobs_out(db: AsyncSession, user_id, jobs: list[Job], matches: dict | None = None) -> list[JobOut]:
    sources = await sources_by_id(db)
    skills = await skills_by_job(db, [job.id for job in jobs])
    if matches is None:
        matches = await matches_by_job(db, user_id, [job.id for job in jobs])
    return [
        job_out(job, sources.get(job.source_id), skills.get(job.id, []), matches.get(job.id))
        for job in jobs
    ]


def application_out(
    app: Application,
    job: dict,
    *,
    approval_expires_at=None,
) -> ApplicationOut:
    return ApplicationOut(
        id=str(app.id),
        job=job,
        status=app.status,
        resume_version_id=str(app.resume_version_id) if app.resume_version_id else None,
        preview=app.preview,
        failure_reason=app.failure_reason,
        outcome=app.outcome,
        approved_at=app.approved_at,
        submitted_at=app.submitted_at,
        confirmed_at=app.confirmed_at,
        submission_attempts=app.submission_attempts,
        screenshot_available=bool(app.screenshot_s3_key or (app.preview or {}).get("worker_session_id")),
        approval_expires_at=approval_expires_at,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


async def application_detail(
    db: AsyncSession, app: Application, job: Job, approval=None
) -> ApplicationDetail:
    answers = (
        await db.execute(
            select(ApplicationAnswer)
            .where(ApplicationAnswer.application_id == app.id)
            .order_by(ApplicationAnswer.created_at)
        )
    ).scalars().all()
    events = (
        await db.execute(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == app.id)
            .order_by(ApplicationEvent.created_at.desc())
            .limit(100)
        )
    ).scalars().all()
    session = (
        await db.execute(
            select(BrowserSession)
            .where(BrowserSession.application_id == app.id)
            .order_by(BrowserSession.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    base = application_out(
        app,
        {
            "id": str(job.id),
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "application_url": job.application_url,
            "source_url": job.source_url,
        },
        approval_expires_at=approval.expires_at if approval else None,
    )
    return ApplicationDetail(
        **base.model_dump(),
        answers=[AnswerOut.model_validate(answer) for answer in answers],
        events=[EventOut.model_validate(event) for event in events],
        confirmation_evidence=app.confirmation_evidence,
        browser_session=(
            {
                "id": str(session.id),
                "status": session.status,
                "last_url": session.last_url,
                "worker_id": session.worker_id,
                "created_at": session.created_at,
                "expired": False,
            }
            if session
            else None
        ),
    )


def match_out(match: JobMatch, job_out_value: JobOut) -> MatchOut:
    return MatchOut(
        id=str(match.id),
        job=job_out_value,
        match_score=match.match_score,
        match_explanation=match.match_explanation,
        is_dismissed=match.is_dismissed,
        created_at=match.created_at,
    )
