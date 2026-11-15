"""
The JobPilot agent graph.

Nine specialised nodes run under LangGraph with checkpointing and a real
human-in-the-loop interrupt before any submission:

  1. resume_intelligence  — is there enough profile data to work with?
  2. job_discovery        — fetch from configured sources
  3. matching             — select the best explainable matches
  4. application_prep     — open, analyse and fill one form
  5. approval             — interrupt; a human must approve with a one-time proof
  6. submission           — only runs with that proof
  7. tracking             — application status roll-up
  8. follow_up            — stale confirmed applications worth chasing
  9. daily_digest         — concise summary for the user

The graph never invents jobs, never fills an unknown required field, and never
submits when the approval node was declined.
"""
from __future__ import annotations

import logging
import operator
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, TypedDict

from fastapi import HTTPException
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import func, select

from app.models.core import (
    AgentRun,
    Application,
    CandidateProfile,
    Job,
    JobMatch,
    ResumeFile,
)
from app.services import applications as app_service
from app.services.discovery import discover
from app.services.search_intent import parse_filters, refine_with_llm

logger = logging.getLogger(__name__)

NODE_LABELS = {
    "resume_intelligence": "Resume intelligence",
    "job_discovery": "Job discovery",
    "matching": "Matching",
    "application_prep": "Application preparation",
    "approval": "Human approval",
    "submission": "Submission",
    "tracking": "Tracking",
    "follow_up": "Follow-up",
    "daily_digest": "Daily digest",
}


class AgentState(TypedDict, total=False):
    goal: str
    user_id: str
    limit: int
    prepare_applications: bool
    filters: dict[str, Any]
    provider: str
    job_ids: list[str]
    top_jobs: list[dict[str, Any]]
    selected_job_id: str | None
    application_id: str | None
    approval_required: bool
    approval_prompt: dict[str, Any] | None
    approved: bool
    proof: dict[str, Any] | None
    submission_outcome: str | None
    tracking_summary: dict[str, Any]
    follow_ups: list[dict[str, Any]]
    digest: dict[str, Any]
    summary: str
    error: str | None
    steps: Annotated[list[dict[str, Any]], operator.add]


_default_checkpointer = MemorySaver()
_checkpointer: Any = _default_checkpointer
_graph = None


def _runtime(config) -> tuple[Any, Any, Any]:
    configurable = config.get("configurable", {})
    return configurable.get("db"), configurable.get("user"), configurable.get("run")


async def _trace(config, node: str, detail: str, status: str = "ok") -> None:
    db, _, run = _runtime(config)
    if run is None:
        return
    run.current_node = node
    trace = list((run.state or {}).get("node_trace") or [])
    trace.append(
        {
            "node": node,
            "label": NODE_LABELS.get(node, node),
            "status": status,
            "detail": detail[:500],
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    run.state = {**(run.state or {}), "node_trace": trace}
    if db is not None:
        await db.commit()


async def resume_intelligence(state: AgentState, config) -> dict:
    db, user, _ = _runtime(config)
    profile = (
        await db.execute(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    ).scalar_one_or_none()
    resume_count = (
        await db.execute(
            select(func.count(ResumeFile.id)).where(
                ResumeFile.user_id == user.id, ResumeFile.deleted_at.is_(None)
            )
        )
    ).scalar_one()
    fields_present = []
    if profile:
        for field in ("full_name", "email", "location", "current_title", "skills", "experience"):
            if getattr(profile, field, None):
                fields_present.append(field)
    if resume_count == 0:
        detail = "No resume on file. Discovery can still run, but applications cannot be prepared."
    else:
        detail = f"{resume_count} resume(s) on file; profile fields: {', '.join(fields_present) or 'none'}."
    await _trace(config, "resume_intelligence", detail)
    return {"steps": [{"node": "resume_intelligence", "detail": detail}]}


async def job_discovery(state: AgentState, config) -> dict:
    db, user, _ = _runtime(config)
    goal = state.get("goal", "")
    low = goal.lower()
    tracking_only = any(word in low for word in ("track", "status of", "follow up", "follow-up")) and not any(
        word in low for word in ("find", "search", "discover", "jobs")
    )
    digest_only = any(word in low for word in ("digest", "daily summary")) and not any(
        word in low for word in ("find", "search", "jobs")
    )
    if tracking_only or digest_only:
        detail = "Goal is tracking/digest only; discovery skipped."
        await _trace(config, "job_discovery", detail)
        return {"steps": [{"node": "job_discovery", "detail": detail}]}

    filters = parse_filters(goal)
    filters, provider = await refine_with_llm(goal, filters)
    outcome = await discover(
        db, user, filters, limit=max(state.get("limit", 5) * 3, 10)
    )
    top = []
    for job, match in outcome.jobs[: state.get("limit", 5)]:
        top.append(
            {
                "job_id": str(job.id),
                "title": job.title,
                "company": job.company,
                "score": match.match_score,
                "url": job.application_url,
            }
        )
    detail = (
        f"{outcome.fetched} listing(s) fetched; {outcome.stored} stored; "
        f"{len(outcome.jobs)} passed filters."
    )
    await _trace(config, "job_discovery", detail)
    return {
        "filters": filters.model_dump(),
        "provider": provider,
        "top_jobs": top,
        "steps": [{"node": "job_discovery", "detail": detail}],
    }


async def matching(state: AgentState, config) -> dict:
    db, user, _ = _runtime(config)
    top = state.get("top_jobs") or []
    if not top:
        rows = (
            await db.execute(
                select(JobMatch, Job)
                .join(Job, Job.id == JobMatch.job_id)
                .where(JobMatch.user_id == user.id, JobMatch.is_dismissed.is_(False))
                .order_by(JobMatch.match_score.desc())
                .limit(state.get("limit", 5))
            )
        ).all()
        top = [
            {
                "job_id": str(row[1].id),
                "title": row[1].title,
                "company": row[1].company,
                "score": row[0].match_score,
                "url": row[1].application_url,
            }
            for row in rows
        ]
    selected = top[0]["job_id"] if top else None
    detail = f"Selected {selected} from {len(top)} candidate(s)." if selected else "No matches available."
    await _trace(config, "matching", detail)
    return {
        "top_jobs": top,
        "selected_job_id": selected,
        "steps": [{"node": "matching", "detail": detail}],
    }


async def application_prep(state: AgentState, config) -> dict:
    db, user, _ = _runtime(config)
    selected = state.get("selected_job_id")
    if not state.get("prepare_applications") or not selected:
        detail = "Application preparation not requested."
        await _trace(config, "application_prep", detail)
        return {"steps": [{"node": "application_prep", "detail": detail}]}

    try:
        try:
            application = await app_service.create_application(db, user, selected)
        except HTTPException as exc:
            if exc.status_code == 409 and isinstance(exc.detail, dict):
                application = await app_service.get_application(
                    db, user.id, exc.detail["application_id"]
                )
            else:
                raise
        job = await app_service.get_job(db, application.job_id)
        if application.status in {"DISCOVERED", "MATCHED", "NEEDS_USER_INPUT"}:
            await app_service.analyze_application(db, user, application)
        if application.status == "FORM_ANALYZED":
            try:
                await app_service.fill_application(db, user, application)
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
        status = application.status
        if status in {"VERIFICATION_PENDING", "FORM_FILLED", "USER_APPROVAL_PENDING"}:
            prompt = {
                "application_id": str(application.id),
                "job": {"title": job.title, "company": job.company, "url": job.application_url},
                "status": status,
                "warnings": (application.preview or {}).get("warnings") or [],
                "missing_required": (application.preview or {}).get("missing_required") or [],
                "resume": (application.preview or {}).get("resume"),
                "instruction": (
                    "Approve with POST /applications/{id}/approval/request then /approve, "
                    "and resume this run with the returned proof."
                ),
            }
            detail = f"Application {application.id} is ready for approval ({status})."
            await _trace(config, "application_prep", detail)
            return {
                "application_id": str(application.id),
                "approval_required": True,
                "approval_prompt": prompt,
                "steps": [{"node": "application_prep", "detail": detail}],
            }
        detail = f"Application {application.id} is not ready for approval ({status})."
        await _trace(config, "application_prep", detail, status="attention")
        return {
            "application_id": str(application.id),
            "approval_required": False,
            "steps": [{"node": "application_prep", "detail": detail}],
        }
    except Exception as exc:
        logger.warning("Agent prep failed: %s", type(exc).__name__)
        detail = f"Preparation stopped: {str(exc)[:200]}"
        await _trace(config, "application_prep", detail, status="error")
        return {"error": detail, "steps": [{"node": "application_prep", "detail": detail}]}


async def approval(state: AgentState, config) -> dict:
    if not state.get("approval_required") or not state.get("application_id"):
        detail = "No submission is waiting for approval."
        await _trace(config, "approval", detail)
        return {"approved": False, "steps": [{"node": "approval", "detail": detail}]}

    decision = interrupt(state.get("approval_prompt") or {})
    db, user, _ = _runtime(config)
    approved = bool((decision or {}).get("approved"))
    proof = (decision or {}).get("proof")
    application_id = (decision or {}).get("application_id") or state.get("application_id")
    if approved and (not proof or proof.get("application_id") != application_id):
        detail = "Approval declined: a matching signed proof is required."
        await _trace(config, "approval", detail, status="attention")
        return {"approved": False, "steps": [{"node": "approval", "detail": detail}]}
    detail = "Approved by user with a signed, one-time proof." if approved else "User declined submission."
    await _trace(config, "approval", detail)
    return {
        "approved": approved,
        "proof": proof,
        "application_id": application_id,
        "steps": [{"node": "approval", "detail": detail}],
    }


async def submission(state: AgentState, config) -> dict:
    db, user, _ = _runtime(config)
    if not state.get("approved") or not state.get("proof") or not state.get("application_id"):
        detail = "No submission performed."
        await _trace(config, "submission", detail)
        return {"steps": [{"node": "submission", "detail": detail}]}
    application = await app_service.get_application(db, user.id, state["application_id"])
    try:
        result = await app_service.submit_application(
            db, user, application, state["proof"]
        )
        outcome = result.get("outcome")
        detail = f"Worker reported: {outcome}."
        await _trace(config, "submission", detail)
        return {
            "submission_outcome": outcome,
            "steps": [{"node": "submission", "detail": detail}],
        }
    except HTTPException as exc:
        detail = f"Submission rejected: {str(exc.detail)[:200]}"
        await _trace(config, "submission", detail, status="error")
        return {"error": detail, "steps": [{"node": "submission", "detail": detail}]}


async def tracking(state: AgentState, config) -> dict:
    db, user, _ = _runtime(config)
    rows = (
        await db.execute(
            select(Application.status, func.count(Application.id))
            .where(Application.user_id == user.id, Application.deleted_at.is_(None))
            .group_by(Application.status)
        )
    ).all()
    counts = {row[0]: row[1] for row in rows}
    detail = ", ".join(f"{key}: {value}" for key, value in counts.items()) or "No applications yet."
    await _trace(config, "tracking", detail)
    return {
        "tracking_summary": {"by_status": counts, "total": sum(counts.values())},
        "steps": [{"node": "tracking", "detail": detail}],
    }


async def follow_up(state: AgentState, config) -> dict:
    db, user, _ = _runtime(config)
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    rows = (
        await db.execute(
            select(Application, Job)
            .join(Job, Job.id == Application.job_id)
            .where(
                Application.user_id == user.id,
                Application.status == "CONFIRMED",
                Application.outcome.is_(None),
                Application.submitted_at.is_not(None),
                Application.submitted_at < cutoff,
                Application.deleted_at.is_(None),
            )
            .order_by(Application.submitted_at)
            .limit(10)
        )
    ).all()
    suggestions = [
        {
            "application_id": str(row[0].id),
            "title": row[1].title,
            "company": row[1].company,
            "submitted_at": row[0].submitted_at.isoformat() if row[0].submitted_at else None,
            "suggestion": "It has been over a week. Check the employer portal or follow up politely by email.",
        }
        for row in rows
    ]
    detail = f"{len(suggestions)} follow-up(s) suggested." if suggestions else "No follow-ups due."
    await _trace(config, "follow_up", detail)
    return {"follow_ups": suggestions, "steps": [{"node": "follow_up", "detail": detail}]}


async def daily_digest(state: AgentState, config) -> dict:
    top = []
    for item in state.get("top_jobs") or []:
        top.append(
            {"title": item.get("title"), "company": item.get("company"), "score": item.get("score")}
        )
    digest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "top_jobs": top,
        "application_status": state.get("tracking_summary", {}).get("by_status", {}),
        "follow_ups": len(state.get("follow_ups") or []),
        "submission_outcome": state.get("submission_outcome"),
    }
    parts = []
    if top:
        parts.append(f"{len(top)} top match(es) ready.")
    if state.get("submission_outcome"):
        parts.append(f"Submission: {state['submission_outcome']}.")
    if state.get("follow_ups"):
        parts.append(f"{len(state['follow_ups'])} follow-up(s) due.")
    summary = " ".join(parts) or "Run complete."
    await _trace(config, "daily_digest", summary)
    return {
        "digest": digest,
        "summary": summary,
        "steps": [{"node": "daily_digest", "detail": summary}],
    }


def configure_checkpointer(checkpointer: Any | None = None) -> None:
    """Install the process checkpointer before serving agent requests."""
    global _checkpointer, _graph
    _checkpointer = checkpointer or _default_checkpointer
    _graph = None


def build_graph(checkpointer: Any | None = None):
    graph = StateGraph(AgentState)
    graph.add_node("resume_intelligence", resume_intelligence)
    graph.add_node("job_discovery", job_discovery)
    graph.add_node("matching", matching)
    graph.add_node("application_prep", application_prep)
    graph.add_node("approval", approval)
    graph.add_node("submission", submission)
    graph.add_node("tracking", tracking)
    graph.add_node("follow_up", follow_up)
    graph.add_node("daily_digest", daily_digest)
    graph.add_edge(START, "resume_intelligence")
    graph.add_edge("resume_intelligence", "job_discovery")
    graph.add_edge("job_discovery", "matching")
    graph.add_edge("matching", "application_prep")
    graph.add_edge("application_prep", "approval")
    graph.add_edge("approval", "submission")
    graph.add_edge("submission", "tracking")
    graph.add_edge("tracking", "follow_up")
    graph.add_edge("follow_up", "daily_digest")
    graph.add_edge("daily_digest", END)
    return graph.compile(checkpointer=checkpointer or _checkpointer)


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("<redacted>" if key in {"proof", "token", "signature", "approval_token"} else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


async def run_agent(db, user, run: AgentRun, *, resume_value: dict | None = None) -> AgentRun:
    graph = get_graph()
    config = {
        "configurable": {
            "thread_id": run.thread_id,
            "db": db,
            "user": user,
            "run": run,
        }
    }
    try:
        if resume_value is None:
            initial: AgentState = {
                "goal": run.goal,
                "user_id": str(user.id),
                "limit": 5,
                "prepare_applications": bool((run.state or {}).get("prepare_applications", False)),
                "steps": [],
            }
            await graph.ainvoke(initial, config)
        else:
            snapshot = await graph.aget_state(config)
            if not snapshot.next:
                raise HTTPException(
                    status_code=409,
                    detail="This run has no checkpoint to resume (it completed or the server restarted).",
                )
            await graph.ainvoke(Command(resume=resume_value), config)

        snapshot = await graph.aget_state(config)
        state = snapshot.values or {}
        run.state = redact({**state, "node_trace": (run.state or {}).get("node_trace", [])})
        run.result = redact(
            {
                "summary": state.get("summary"),
                "top_jobs": state.get("top_jobs"),
                "tracking_summary": state.get("tracking_summary"),
                "follow_ups": state.get("follow_ups"),
                "digest": state.get("digest"),
                "submission_outcome": state.get("submission_outcome"),
                "approved": state.get("approved"),
                "application_id": state.get("application_id"),
                "error": state.get("error"),
            }
        )
        interrupts = [task.interrupts[0] for task in snapshot.tasks if task.interrupts]
        if interrupts:
            run.status = "awaiting_approval"
            run.current_node = snapshot.next[0] if snapshot.next else "approval"
            run.interrupt_payload = interrupts[0].value
            run.completed_at = None
        else:
            state_error = state.get("error")
            if state_error and not run.error:
                run.error = state_error
            run.status = "completed" if not run.error else "failed"
            run.current_node = snapshot.next[0] if snapshot.next else "completed"
            run.interrupt_payload = None
            run.completed_at = datetime.now(timezone.utc)
    except HTTPException as exc:
        run.status = "failed"
        run.error = str(exc.detail)
        run.completed_at = datetime.now(timezone.utc)
    except Exception as exc:
        logger.exception("Agent run failed")
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {str(exc)[:300]}"
        run.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(run)
    return run



