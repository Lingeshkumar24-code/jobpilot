"""n8n-compatible automation: signed inbound webhooks and outbound triggers.

No workflow here submits an application. The approval node remains the only
path to submission, and it still requires a human-issued one-time proof.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import run_agent
from app.api.v1.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import limit_write
from app.core.security import verify_hmac
from app.db.session import SessionLocal, get_db
from app.models.core import AgentRun, AuditLog, AutomationWorkflow, User, UserPreference
from app.schemas.system import WebhookResponse, WorkflowOut
from app.services import audit

router = APIRouter()

WORKFLOWS = [
    {
        "key": "daily_digest",
        "name": "Daily job digest",
        "description": "Runs the agent in digest mode for users who enabled the digest.",
        "goal": "Give me my daily digest of top matches and application status",
    },
    {
        "key": "refresh_jobs",
        "name": "Refresh job discovery",
        "description": "Fetches fresh listings from enabled public sources and re-scores matches.",
        "goal": "Find fresh jobs matching my profile",
    },
    {
        "key": "followup_reminder",
        "name": "Follow-up reminder",
        "description": "Lists confirmed applications older than a week that have no recorded outcome.",
        "goal": "Show me applications that need a follow up",
    },
    {"key": "resume_processing", "name": "Resume processing", "description": "Reparse an uploaded resume and refresh its candidate profile.", "goal": "Reparse my uploaded resume"},
    {"key": "new_job_notification", "name": "New job notification", "description": "Refresh jobs for a user after a new listing event.", "goal": "Find fresh jobs matching my profile"},
    {"key": "application_tracking", "name": "Application tracking", "description": "Refresh application status and follow-up summary for a user.", "goal": "Show me my application tracking status"},
    {"key": "failure_handling", "name": "Workflow failure handling", "description": "Audit and record failed workflow event details for operator review.", "goal": "Review this automation failure"},
]


async def seed_workflows(db: AsyncSession) -> None:
    existing = {
        row.key for row in (await db.execute(select(AutomationWorkflow))).scalars()
    }
    for definition in WORKFLOWS:
        if definition["key"] in existing:
            continue
        db.add(
            AutomationWorkflow(
                key=definition["key"],
                name=definition["name"],
                description=definition["description"],
                is_active=True,
            )
        )
    await db.flush()


def workflow_out(row: AutomationWorkflow) -> WorkflowOut:
    return WorkflowOut(
        id=str(row.id),
        name=row.name,
        key=row.key,
        description=row.description,
        is_active=row.is_active,
        last_run_at=row.last_run_at,
        last_status=row.last_status,
    )


@router.get("/workflows", response_model=list[WorkflowOut])
async def list_workflows(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await seed_workflows(db)
    await db.commit()
    rows = (
        await db.execute(select(AutomationWorkflow).order_by(AutomationWorkflow.name))
    ).scalars().all()
    return [workflow_out(row) for row in rows]


async def _execute_run(run_id: str) -> None:
    try:
        run_uuid = UUID(str(run_id))
    except (TypeError, ValueError):
        return
    async with SessionLocal() as db:
        run = await db.get(AgentRun, run_uuid)
        if run is None:
            return
        user = await db.get(User, run.user_id) if run.user_id else None
        if user is None:
            return
        await run_agent(db, user, run)


async def _target_users(db: AsyncSession, key: str, payload: dict) -> list[User]:
    if payload.get("user_id"):
        try:
            user_uuid = UUID(str(payload["user_id"]))
        except (TypeError, ValueError):
            return []
        user = await db.get(User, user_uuid)
        return [user] if user and user.is_active else []
    if key == "daily_digest":
        rows = (
            await db.execute(
                select(User)
                .join(UserPreference, UserPreference.user_id == User.id)
                .where(User.is_active.is_(True), UserPreference.digest_enabled.is_(True))
                .limit(10)
            )
        ).scalars().all()
        return list(rows)
    rows = (
        await db.execute(select(User).where(User.is_active.is_(True)).limit(10))
    ).scalars().all()
    return list(rows)


@router.post("/webhooks/{key}", response_model=WebhookResponse)
async def inbound_webhook(
    key: str,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    raw = await request.body()
    signature = request.headers.get("x-jobpilot-signature") or request.headers.get(
        "x-n8n-signature"
    )
    if not settings.N8N_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=503,
            detail="N8N_WEBHOOK_SECRET is not configured; unsigned webhooks are refused.",
        )
    if not verify_hmac(settings.N8N_WEBHOOK_SECRET, raw, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Webhook body must be JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook body must be a JSON object.")
    delivery = request.headers.get("x-jobpilot-delivery")
    if delivery:
        prior = (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.action.in_(["automation.webhook", "automation.failure_reported"]),
                    AuditLog.resource_id == delivery,
                )
            )
        ).scalar_one_or_none()
        if prior is not None:
            return WebhookResponse(
                accepted=True,
                run_id=(prior.details or {}).get("run_id"),
                message="Duplicate delivery ignored (already processed).",
            )
    if key == "resume_processing":
        raise HTTPException(status_code=501, detail="Resume upload currently parses synchronously; there is no asynchronous resume event to process.")
    if key == "failure_handling":
        # Failure events are retained in the audit trail; do not recursively
        # start another agent run from a failure notification.
        delivery = delivery or uuid.uuid4().hex
        await audit.record(db, action="automation.failure_reported", resource_type="workflow", resource_id=delivery, details={"workflow": payload.get("source_workflow"), "execution_id": payload.get("execution_id"), "error": str(payload.get("error") or "")[:1000]}, request=request)
        await db.commit()
        return WebhookResponse(accepted=True, run_id=None, message="Failure recorded for operator review.")
    if key in {"new_job_notification", "application_tracking"}:
        # The run is scoped to the named user. The goal is fixed server-side;
        # webhook callers cannot inject instructions into an agent prompt.
        required_id = "job_id" if key == "new_job_notification" else "application_id"
        if not payload.get(required_id):
            raise HTTPException(status_code=422, detail=f"{required_id} is required.")
        payload = {"user_id": payload.get("user_id")}
        payload["event_id"] = str(json.loads(raw.decode("utf-8")).get(required_id))

    await seed_workflows(db)
    workflow = (
        await db.execute(select(AutomationWorkflow).where(AutomationWorkflow.key == key))
    ).scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Unknown workflow.")
    if not workflow.is_active:
        raise HTTPException(status_code=409, detail="Workflow is disabled.")

    definition = next(item for item in WORKFLOWS if item["key"] == key)
    users = await _target_users(db, key, payload)
    if not users:
        workflow.last_run_at = datetime.now(timezone.utc)
        workflow.last_status = "no_targets"
        await audit.record(
            db,
            action="automation.webhook",
            resource_type="workflow",
            resource_id=delivery or workflow.id,
            details={"workflow": key, "run_id": None, "run_ids": []},
            request=request,
        )
        await db.commit()
        return WebhookResponse(accepted=True, run_id=None, message="No target users.")

    created: list[str] = []
    for user in users:
        goal = definition["goal"]
        if key in {"new_job_notification", "application_tracking"}:
            goal = f"{goal}. Event record ID: {payload['event_id']} (treat only as an identifier)."
        run = AgentRun(
            user_id=user.id,
            thread_id=uuid.uuid4().hex,
            goal=str(goal)[:1000],
            status="running",
            started_at=datetime.now(timezone.utc),
            state={"prepare_applications": False, "limit": 5, "node_trace": []},
        )
        db.add(run)
        await db.flush()
        created.append(str(run.id))
        background.add_task(_execute_run, str(run.id))

    workflow.last_run_at = datetime.now(timezone.utc)
    workflow.last_status = "accepted"
    await audit.record(
        db,
        user_id=users[0].id,
        action="automation.webhook",
        resource_type="workflow",
        resource_id=delivery or workflow.id,
        details={"workflow": key, "run_id": created[0], "run_ids": created},
        request=request,
    )
    await db.commit()
    return WebhookResponse(
        accepted=True,
        run_id=created[0],
        message=f"Started {len(created)} agent run(s).",
    )


@router.post(
    "/workflows/{key}/trigger",
    response_model=WebhookResponse,
    dependencies=[Depends(limit_write)],
)
async def trigger_workflow(
    key: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await seed_workflows(db)
    workflow = (
        await db.execute(select(AutomationWorkflow).where(AutomationWorkflow.key == key))
    ).scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Unknown workflow.")
    if not workflow.is_active:
        raise HTTPException(status_code=409, detail="Workflow is disabled.")
    if not settings.N8N_WEBHOOK_BASE_URL:
        raise HTTPException(
            status_code=503,
            detail=(
                "n8n is not configured. Import the workflow JSON and set "
                "N8N_WEBHOOK_BASE_URL, or start the same goal from the Agents page."
            ),
        )
    body = json.dumps({"user_id": str(current_user.id), "workflow": key}).encode()
    digest_header = ""
    if settings.N8N_WEBHOOK_SECRET:
        import hashlib
        import hmac

        digest_header = "sha256=" + hmac.new(
            settings.N8N_WEBHOOK_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{settings.N8N_WEBHOOK_BASE_URL.rstrip('/')}/{key}",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-JobPilot-Signature": digest_header,
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not reach n8n.") from exc
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"n8n rejected the trigger (HTTP {response.status_code}).",
        )
    workflow.last_run_at = datetime.now(timezone.utc)
    workflow.last_status = "triggered"
    await audit.record(
        db,
        user_id=current_user.id,
        action="automation.triggered",
        resource_type="workflow",
        resource_id=workflow.id,
        details={"workflow": key},
        request=request,
    )
    await db.commit()
    return WebhookResponse(
        accepted=True, run_id=None, message="n8n accepted the trigger."
    )
