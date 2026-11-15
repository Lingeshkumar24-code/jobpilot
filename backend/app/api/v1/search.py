"""Natural-language search: interpret, execute, and keep a runnable history."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from uuid import UUID
from sqlalchemy import delete as sql_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.rate_limit import limit_search
from app.db.session import get_db
from app.models.core import SearchQuery, User
from app.schemas.search import (
    SaveSearchRequest,
    SearchExecuteRequest,
    SearchExecutionResponse,
    SearchHistoryItem,
    SearchIntentRequest,
    SearchIntentResponse,
    SearchResultJob,
    StructuredFilters,
)
from app.services import audit
from app.services.discovery import discover
from app.services.search_intent import merge_refinement, parse_intent, refine_with_llm
from app.services.serializers import job_out, matches_by_job, skills_by_job, sources_by_id

router = APIRouter()


@router.post("/intent", response_model=SearchIntentResponse)
async def interpret_query(
    payload: SearchIntentRequest,
    current_user: User = Depends(get_current_user),
):
    filters, provider = parse_intent(payload.query)
    if provider == "rule_based":
        filters, provider = await refine_with_llm(payload.query, filters)
    if payload.previous_filters:
        filters = merge_refinement(payload.previous_filters, filters)
    missing = []
    if not filters.role:
        missing.append("role")
    if not filters.location and "remote" not in filters.work_mode:
        missing.append("location")
    return SearchIntentResponse(
        query=payload.query, filters=filters, provider=provider, missing=missing
    )


@router.post(
    "/execute",
    response_model=SearchExecutionResponse,
    dependencies=[Depends(limit_search)],
)
async def execute_search(
    payload: SearchExecuteRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    filters, provider = parse_intent(payload.query)
    if provider == "rule_based":
        filters, provider = await refine_with_llm(payload.query, filters)
    if payload.previous_filters:
        filters = merge_refinement(payload.previous_filters, filters)

    query_row = SearchQuery(
        user_id=current_user.id,
        raw_text=payload.query,
        structured_filters=filters.model_dump(),
        intent_provider=provider,
        name=payload.name,
        is_saved=payload.save,
        last_run_at=datetime.now(timezone.utc),
    )
    db.add(query_row)
    await db.flush()

    outcome = await discover(
        db,
        current_user,
        filters,
        source_keys=payload.sources,
        limit=payload.limit,
    )
    query_row.result_count = len(outcome.jobs)

    sources = await sources_by_id(db)
    jobs = [job for job, _ in outcome.jobs]
    skills = await skills_by_job(db, [job.id for job in jobs])
    matches = await matches_by_job(db, current_user.id, [job.id for job in jobs])
    jobs_payload = [
        SearchResultJob(
            **job_out(job, sources.get(job.source_id), skills.get(job.id, []), matches.get(job.id)).model_dump()
        )
        for job in jobs
    ]

    await audit.record(
        db,
        user_id=current_user.id,
        action="search.executed",
        resource_type="search",
        resource_id=query_row.id,
        details={
            "query": payload.query[:200],
            "filters": filters.model_dump(),
            "provider": provider,
            "results": len(jobs),
            "sources": [s["key"] for s in outcome.sources if s["status"] == "ok"],
        },
        request=request,
    )
    await db.commit()
    return SearchExecutionResponse(
        query_id=str(query_row.id),
        filters=filters,
        provider=provider,
        jobs=jobs_payload,
        sources=outcome.sources,
        warnings=outcome.warnings,
        total=len(jobs),
    )


@router.get("/history", response_model=list[SearchHistoryItem])
async def search_history(
    limit: int = 25,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(SearchQuery)
            .where(SearchQuery.user_id == current_user.id, SearchQuery.deleted_at.is_(None))
            .order_by(SearchQuery.created_at.desc())
            .limit(min(limit, 100))
        )
    ).scalars().all()
    return [SearchHistoryItem.model_validate(row) for row in rows]


@router.patch("/history/{query_id}", response_model=SearchHistoryItem)
async def save_search(
    query_id: UUID,
    payload: SaveSearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(SearchQuery).where(
                SearchQuery.id == query_id,
                SearchQuery.user_id == current_user.id,
                SearchQuery.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Search not found")
    row.name = payload.name
    row.is_saved = True
    await db.commit()
    await db.refresh(row)
    return SearchHistoryItem.model_validate(row)


@router.delete("/history/{query_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_search(
    query_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(SearchQuery).where(
                SearchQuery.id == query_id, SearchQuery.user_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Search not found")
    await db.execute(sql_delete(SearchQuery).where(SearchQuery.id == row.id))
    await db.commit()
    return None


@router.get("/saved", response_model=list[SearchHistoryItem])
async def saved_searches(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(SearchQuery)
            .where(
                SearchQuery.user_id == current_user.id,
                SearchQuery.is_saved.is_(True),
                SearchQuery.deleted_at.is_(None),
            )
            .order_by(SearchQuery.created_at.desc())
        )
    ).scalars().all()
    return [SearchHistoryItem.model_validate(row) for row in rows]


@router.post("/refine", response_model=SearchIntentResponse)
async def refine(
    payload: SearchIntentRequest,
    current_user: User = Depends(get_current_user),
):
    base = payload.previous_filters or StructuredFilters()
    filters, provider = parse_intent(payload.query)
    if provider == "rule_based":
        filters, provider = await refine_with_llm(payload.query, filters)
    merged = merge_refinement(base, filters)
    return SearchIntentResponse(query=payload.query, filters=merged, provider=provider, missing=[])

