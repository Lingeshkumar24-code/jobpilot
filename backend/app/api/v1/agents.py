"""Agent run endpoints (LangGraph, checkpointed, human-in-the-loop)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import NODE_LABELS, run_agent
from app.api.v1.deps import get_current_user
from app.core.rate_limit import limit_write
from app.db.session import get_db
from app.models.core import AgentRun, User
from app.schemas.system import AgentResumeRequest, AgentRunList, AgentRunOut, AgentRunRequest
from app.services import audit

router = APIRouter()


def run_out(run: AgentRun) -> AgentRunOut:
    trace = (run.state or {}).get("node_trace") or []
    return AgentRunOut(
        id=str(run.id),
        thread_id=run.thread_id,
        goal=run.goal,
        status=run.status,
        current_node=run.current_node,
        state=run.state,
        result=run.result,
        interrupt_payload=run.interrupt_payload,
        error=run.error,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        steps=[
            {
                "node": step.get("node", "unknown"),
                "label": step.get("label") or NODE_LABELS.get(step.get("node"), "Step"),
                "status": step.get("status", "ok"),
                "detail": step.get("detail"),
                "at": step.get("at") or datetime.now(timezone.utc).isoformat(),
            }
            for step in trace
        ],
    )


async def _owned_run(db: AsyncSession, user: User, run_id: UUID) -> AgentRun:
    run = (
        await db.execute(
            select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user.id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


@router.post(
    "/runs",
    response_model=AgentRunOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_write)],
)
async def start_run(
    payload: AgentRunRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = AgentRun(
        user_id=current_user.id,
        thread_id=uuid.uuid4().hex,
        goal=payload.goal.strip(),
        status="running",
        started_at=datetime.now(timezone.utc),
        state={
            "prepare_applications": payload.prepare_applications,
            "limit": payload.limit,
            "node_trace": [],
        },
    )
    db.add(run)
    await db.flush()
    await audit.record(
        db,
        user_id=current_user.id,
        action="agent.started",
        resource_type="agent_run",
        resource_id=run.id,
        details={"goal": run.goal[:200], "prepare_applications": payload.prepare_applications},
        request=request,
    )
    await db.commit()
    await db.refresh(run)
    run = await run_agent(db, current_user, run)
    return run_out(run)


@router.get("/runs", response_model=AgentRunList)
async def list_runs(
    limit: int = 25,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(AgentRun)
            .where(AgentRun.user_id == current_user.id)
            .order_by(AgentRun.created_at.desc())
            .limit(min(max(limit, 1), 100))
        )
    ).scalars().all()
    return AgentRunList(runs=[run_out(row) for row in rows], total=len(rows))


@router.get("/runs/{run_id}", response_model=AgentRunOut)
async def get_run(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return run_out(await _owned_run(db, current_user, run_id))


@router.post(
    "/runs/{run_id}/resume",
    response_model=AgentRunOut,
    dependencies=[Depends(limit_write)],
)
async def resume_run(
    run_id: UUID,
    payload: AgentResumeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _owned_run(db, current_user, run_id)
    if run.status != "awaiting_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Run is '{run.status}', not waiting for approval.",
        )
    expected_application_id = (run.state or {}).get("application_id") or (
        run.interrupt_payload or {}
    ).get("application_id")
    if payload.application_id and expected_application_id and payload.application_id != expected_application_id:
        raise HTTPException(status_code=400, detail="Application does not match this run.")
    if payload.approved and not payload.proof:
        raise HTTPException(
            status_code=400,
            detail=(
                "Approval requires the signed proof from POST /applications/{id}/approve. "
                "Approve the application first."
            ),
        )
    if payload.approved and payload.proof.get("application_id") != expected_application_id:
        raise HTTPException(status_code=400, detail="Approval proof is for a different application.")

    resume_value = {
        "approved": payload.approved,
        "application_id": payload.application_id or expected_application_id,
        "proof": payload.proof,
        "note": payload.note,
    }
    run.status = "running"
    await audit.record(
        db,
        user_id=current_user.id,
        action="agent.resumed",
        resource_type="agent_run",
        resource_id=run.id,
        details={"approved": payload.approved, "application_id": expected_application_id},
        request=request,
    )
    await db.commit()
    run = await run_agent(db, current_user, run, resume_value=resume_value)
    return run_out(run)


@router.post(
    "/runs/{run_id}/cancel",
    response_model=AgentRunOut,
    dependencies=[Depends(limit_write)],
)
async def cancel_run(
    run_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _owned_run(db, current_user, run_id)
    if run.status == "awaiting_approval":
        run = await run_agent(
            db,
            current_user,
            run,
            resume_value={
                "approved": False,
                "application_id": (run.state or {}).get("application_id"),
                "proof": None,
                "note": "Cancelled by the user.",
            },
        )
    if run.status not in {"completed", "failed"}:
        run.status = "cancelled"
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(run)
    await audit.record(
        db,
        user_id=current_user.id,
        action="agent.cancelled",
        resource_type="agent_run",
        resource_id=run.id,
        request=request,
    )
    await db.commit()
    return run_out(run)

