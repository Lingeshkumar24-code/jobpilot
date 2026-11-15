"""Ranked, explainable matches."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from uuid import UUID
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.core import Job, JobMatch, User
from app.schemas.jobs import MatchListResponse, MatchOut, MatchStats
from app.services.serializers import jobs_out

router = APIRouter()


@router.get("", response_model=MatchListResponse)
async def list_matches(
    q: str | None = Query(default=None, max_length=200),
    min_score: float = Query(default=0, ge=0, le=100),
    include_dismissed: bool = False,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conditions = [JobMatch.user_id == current_user.id, JobMatch.match_score >= min_score]
    if not include_dismissed:
        conditions.append(JobMatch.is_dismissed.is_(False))
    query = (
        select(JobMatch, Job)
        .join(Job, Job.id == JobMatch.job_id)
        .where(*conditions)
        .order_by(JobMatch.match_score.desc(), JobMatch.created_at.desc())
    )
    count_query = (
        select(func.count(JobMatch.id))
        .join(Job, Job.id == JobMatch.job_id)
        .where(*conditions)
    )
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(or_(Job.title.ilike(pattern), Job.company.ilike(pattern)))
        count_query = count_query.where(or_(Job.title.ilike(pattern), Job.company.ilike(pattern)))
    rows = (await db.execute(query.limit(limit).offset(offset))).all()
    total = (await db.execute(count_query)).scalar_one()
    jobs = [row[1] for row in rows]
    payload = await jobs_out(db, current_user.id, jobs)
    matches = [
        MatchOut(
            id=str(row[0].id),
            job=payload[index],
            match_score=row[0].match_score,
            match_explanation=row[0].match_explanation,
            is_dismissed=row[0].is_dismissed,
            created_at=row[0].created_at,
        )
        for index, row in enumerate(rows)
    ]
    return MatchListResponse(matches=matches, total=total)


@router.get("/stats", response_model=MatchStats)
async def match_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    total = (
        await db.execute(select(func.count(JobMatch.id)).where(JobMatch.user_id == current_user.id))
    ).scalar_one()
    dismissed = (
        await db.execute(
            select(func.count(JobMatch.id)).where(
                JobMatch.user_id == current_user.id, JobMatch.is_dismissed.is_(True)
            )
        )
    ).scalar_one()
    average = (
        await db.execute(
            select(func.avg(JobMatch.match_score)).where(
                JobMatch.user_id == current_user.id, JobMatch.is_dismissed.is_(False)
            )
        )
    ).scalar()
    above = (
        await db.execute(
            select(func.count(JobMatch.id)).where(
                JobMatch.user_id == current_user.id,
                JobMatch.is_dismissed.is_(False),
                JobMatch.match_score >= 55,
            )
        )
    ).scalar_one()
    return MatchStats(
        total=total,
        dismissed=dismissed,
        scored_today=total,
        average_score=round(float(average), 1) if average is not None else None,
        above_threshold=above,
    )


@router.get("/{match_id}", response_model=MatchOut)
async def get_match(
    match_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(JobMatch, Job)
            .join(Job, Job.id == JobMatch.job_id)
            .where(JobMatch.id == match_id, JobMatch.user_id == current_user.id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Match not found")
    payload = (await jobs_out(db, current_user.id, [row[1]]))[0]
    return MatchOut(
        id=str(row[0].id),
        job=payload,
        match_score=row[0].match_score,
        match_explanation=row[0].match_explanation,
        is_dismissed=row[0].is_dismissed,
        created_at=row[0].created_at,
    )


@router.post("/{match_id}/dismiss", response_model=MatchOut)
async def dismiss_match(
    match_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    match = (
        await db.execute(
            select(JobMatch).where(
                JobMatch.id == match_id, JobMatch.user_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    match.is_dismissed = True
    await db.commit()
    await db.refresh(match)
    return await get_match(match_id, current_user, db)


@router.post("/{match_id}/undismiss", response_model=MatchOut)
async def undismiss_match(
    match_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    match = (
        await db.execute(
            select(JobMatch).where(
                JobMatch.id == match_id, JobMatch.user_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    match.is_dismissed = False
    await db.commit()
    await db.refresh(match)
    return await get_match(match_id, current_user, db)

