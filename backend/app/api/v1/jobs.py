"""Job catalogue: browse what discovery actually stored, with provenance."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from uuid import UUID
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.core import Job, JobMatch, JobSkill, JobSource, User
from app.schemas.jobs import JobDetailResponse, JobListResponse, SourceOut
from app.services.job_sources import source_metadata
from app.services.serializers import job_out, jobs_out, sources_by_id
from app.services.skills import extract_skills

router = APIRouter()


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = {row.connector_key: row for row in (await db.execute(select(JobSource))).scalars()}
    metadata = {item["key"]: item for item in source_metadata()}
    result: list[SourceOut] = []
    for key, meta in metadata.items():
        row = rows.get(key)
        result.append(
            SourceOut(
                key=key,
                display_name=meta["display_name"],
                base_url=meta["base_url"],
                attribution=meta["attribution"],
                requires_credentials=meta["requires_credentials"],
                is_enabled=row.is_enabled if row else True,
                configured=meta["configured"],
                last_synced_at=row.last_synced_at if row else None,
                last_sync_error=row.last_sync_error if row else None,
                notes=meta["notes"],
            )
        )
    return result


@router.get("", response_model=JobListResponse)
async def list_jobs(
    q: str | None = Query(default=None, max_length=200),
    source: str | None = Query(default=None, max_length=80),
    location: str | None = Query(default=None, max_length=120),
    work_mode: str | None = Query(default=None, max_length=20),
    employment_type: str | None = Query(default=None, max_length=20),
    min_score: float | None = Query(default=None, ge=0, le=100),
    include_inactive: bool = False,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conditions = [Job.deleted_at.is_(None)]
    if not include_inactive:
        conditions.append(Job.is_active.is_(True))
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(or_(Job.title.ilike(pattern), Job.company.ilike(pattern)))
    if location:
        conditions.append(Job.location.ilike(f"%{location.strip()}%"))
    if work_mode:
        conditions.append(Job.work_mode == work_mode)
    if employment_type:
        conditions.append(Job.employment_type == employment_type)

    query = (
        select(Job, JobMatch)
        .outerjoin(
            JobMatch,
            and_(JobMatch.job_id == Job.id, JobMatch.user_id == current_user.id),
        )
        .where(*conditions)
    )
    count_query = select(func.count(Job.id)).where(*conditions)
    if source:
        query = query.join(JobSource, JobSource.id == Job.source_id).where(
            JobSource.connector_key == source
        )
        count_query = count_query.join(JobSource, JobSource.id == Job.source_id).where(
            JobSource.connector_key == source
        )
    if min_score is not None:
        query = query.where(JobMatch.match_score >= min_score)
        count_query = (
            count_query.outerjoin(
                JobMatch,
                and_(JobMatch.job_id == Job.id, JobMatch.user_id == current_user.id),
            ).where(JobMatch.match_score >= min_score)
        )

    query = query.order_by(Job.posted_at.desc().nullslast(), Job.first_seen_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(query)).all()
    total = (await db.execute(count_query)).scalar_one()
    jobs = [row[0] for row in rows]
    match_map = {row[0].id: row[1] for row in rows if row[1] is not None}
    payload = await jobs_out(db, current_user.id, jobs, match_map)
    return JobListResponse(jobs=payload, total=total, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=JobDetailResponse)
async def get_job(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = (
        await db.execute(
            select(Job).where(Job.id == job_id, Job.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    source = (await sources_by_id(db)).get(job.source_id)
    skills = list(
        (await db.execute(select(JobSkill.skill).where(JobSkill.job_id == job.id))).scalars()
    )
    if not skills:
        skills = extract_skills(f"{job.title} {job.description or ''}")
    match = (
        await db.execute(
            select(JobMatch).where(JobMatch.job_id == job.id, JobMatch.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    return JobDetailResponse(
        job=job_out(job, source, skills, match),
        source_attribution=source.attribution if source else None,
        duplicates=job.duplicate_sources or [],
    )


@router.get("/{job_id}/skills", response_model=list[str])
async def job_skills(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = (
        await db.execute(select(Job).where(Job.id == job_id, Job.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    skills = list(
        (await db.execute(select(JobSkill.skill).where(JobSkill.job_id == job.id))).scalars()
    )
    return skills or extract_skills(f"{job.title} {job.description or ''}")


