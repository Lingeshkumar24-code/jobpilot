"""
Application endpoints. Every submission is gated by an explicit, per-
application, one-time approval and executed by the isolated browser worker.
"""
from __future__ import annotations

import io
import asyncio
import contextlib
import logging
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from uuid import UUID
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.constants import APPLICATION_STATUSES
from app.core.config import settings
from app.core.rate_limit import limit_write
from app.db.session import get_db
from app.models.core import Application, ApplicationAnswer, ApplicationEvent, Approval, BrowserSession, Job, User
from app.schemas.application import (
    AnswerOut,
    AnswerUpdate,
    ApplicationDetail,
    ApplicationListResponse,
    ApplicationOut,
    ApplicationStats,
    ApproveRequest,
    ApproveResponse,
    CreateApplicationRequest,
    ManualConfirmRequest,
    OutcomeRequest,
    RejectRequest,
    SubmitRequest,
    SubmitResponse,
)
from app.services import applications as app_service
from app.services.serializers import application_detail, application_out
from app.services.storage import StorageError, storage
from app.services.browser_client import BrowserClient, BrowserWorkerError, decode_screenshot

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/{application_id}/browser-stream-ticket")
async def browser_stream_ticket(
    application_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_service.get_application(db, current_user.id, application_id)
    session = (
        await db.execute(
            select(BrowserSession)
            .where(BrowserSession.application_id == app.id)
            .order_by(BrowserSession.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if session is None or not session.session_ref or not session.worker_id or session.status == "BLOCKED":
        raise HTTPException(status_code=404, detail="Live browser session is not available.")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)
    ticket = jwt.encode(
        {
            "typ": "browser_stream",
            "sub": str(current_user.id),
            "application_id": str(app.id),
            "session_id": session.session_ref,
            "worker_id": session.worker_id,
            "exp": expires_at,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"ticket": ticket, "expires_at": expires_at.isoformat()}


@router.websocket("/{application_id}/browser-stream")
async def browser_stream(websocket: WebSocket, application_id: UUID):
    raw_ticket = websocket.query_params.get("ticket", "")
    try:
        claims = jwt.decode(raw_ticket, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        if claims.get("typ") != "browser_stream" or claims.get("application_id") != str(application_id):
            raise JWTError("Invalid browser stream ticket")
        worker_id = claims["worker_id"].rstrip("/")
        worker_parts = urlsplit(worker_id)
        if worker_parts.hostname == "localhost":
            netloc = f"127.0.0.1:{worker_parts.port}" if worker_parts.port else "127.0.0.1"
            worker_id = urlunsplit((worker_parts.scheme, netloc, worker_parts.path, "", ""))
        session_id = claims["session_id"]
    except (JWTError, KeyError, TypeError):
        await websocket.close(code=4401, reason="Invalid or expired browser stream ticket")
        return

    await websocket.accept()
    try:
        from websockets.asyncio.client import connect as websocket_connect

        async with websocket_connect(
            f"{worker_id.replace('http://', 'ws://').replace('https://', 'wss://')}/v1/sessions/{session_id}/stream",
            additional_headers={"X-Worker-Secret": settings.BROWSER_WORKER_SECRET},
            max_size=8 * 1024 * 1024,
        ) as upstream:
            async def worker_to_user():
                while True:
                    await websocket.send_text(await upstream.recv())

            async def user_to_worker():
                while True:
                    await upstream.send(await websocket.receive_text())

            tasks = [asyncio.create_task(worker_to_user()), asyncio.create_task(user_to_worker())]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if not task.cancelled() and task.exception():
                        raise task.exception()
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Browser stream proxy failed for application %s", application_id)
        with contextlib.suppress(Exception):
            await websocket.close(code=1011, reason="Browser stream ended")


async def _job(db: AsyncSession, job_id) -> Job:
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _approval(db: AsyncSession, application_id):
    return (
        await db.execute(select(Approval).where(Approval.application_id == application_id))
    ).scalar_one_or_none()


@router.post("", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: CreateApplicationRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_service.create_application(
        db, current_user, payload.job_id, payload.resume_version_id, request
    )
    job = await _job(db, app.job_id)
    return application_out(app, {"id": str(job.id), "title": job.title, "company": job.company, "location": job.location, "application_url": job.application_url})


@router.get("", response_model=ApplicationListResponse)
async def list_applications(
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conditions = [Application.user_id == current_user.id, Application.deleted_at.is_(None)]
    if status_filter:
        if status_filter not in APPLICATION_STATUSES:
            raise HTTPException(status_code=422, detail="Unknown application status")
        conditions.append(Application.status == status_filter)
    query = (
        select(Application, Job)
        .join(Job, Job.id == Application.job_id)
        .where(*conditions)
        .order_by(Application.updated_at.desc())
    )
    count_query = (
        select(func.count(Application.id))
        .join(Job, Job.id == Application.job_id)
        .where(*conditions)
    )
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(or_(Job.title.ilike(pattern), Job.company.ilike(pattern)))
        count_query = count_query.where(or_(Job.title.ilike(pattern), Job.company.ilike(pattern)))
    rows = (await db.execute(query.limit(limit).offset(offset))).all()
    total = (await db.execute(count_query)).scalar_one()
    counts = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(Application.status, func.count(Application.id))
                .where(Application.user_id == current_user.id, Application.deleted_at.is_(None))
                .group_by(Application.status)
            )
        ).all()
    }
    apps = [
        application_out(
            row[0],
            {
                "id": str(row[1].id),
                "title": row[1].title,
                "company": row[1].company,
                "location": row[1].location,
                "application_url": row[1].application_url,
            },
        )
        for row in rows
    ]
    return ApplicationListResponse(applications=apps, total=total, counts=counts)


@router.get("/stats", response_model=ApplicationStats)
async def application_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(Application.status, func.count(Application.id))
            .where(Application.user_id == current_user.id, Application.deleted_at.is_(None))
            .group_by(Application.status)
        )
    ).all()
    by_status = {row[0]: row[1] for row in rows}
    outcomes = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(Application.outcome, func.count(Application.id))
                .where(
                    Application.user_id == current_user.id,
                    Application.deleted_at.is_(None),
                    Application.outcome.is_not(None),
                )
                .group_by(Application.outcome)
            )
        ).all()
    }
    return ApplicationStats(
        total=sum(by_status.values()),
        by_status=by_status,
        confirmed=by_status.get("CONFIRMED", 0),
        needs_input=by_status.get("NEEDS_USER_INPUT", 0) + by_status.get("CAPTCHA_REQUIRED", 0) + by_status.get("LOGIN_REQUIRED", 0),
        pending_approval=by_status.get("USER_APPROVAL_PENDING", 0) + by_status.get("APPROVED", 0),
        interviews=outcomes.get("interview", 0),
        offers=outcomes.get("offer", 0),
    )


@router.get("/{application_id}", response_model=ApplicationDetail)
async def get_application(
    application_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_service.get_application(db, current_user.id, application_id)
    job = await _job(db, app.job_id)
    approval = await _approval(db, app.id)
    return await application_detail(db, app, job, approval)


@router.get("/{application_id}/events", response_model=list[dict])
async def get_events(
    application_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_service.get_application(db, current_user.id, application_id)
    events = (
        await db.execute(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == app.id)
            .order_by(ApplicationEvent.created_at.desc())
            .limit(200)
        )
    ).scalars().all()
    return [
        {
            "id": str(event.id),
            "event_type": event.event_type,
            "from_status": event.from_status,
            "to_status": event.to_status,
            "actor": event.actor,
            "payload": event.payload,
            "created_at": event.created_at,
        }
        for event in events
    ]


@router.post(
    "/{application_id}/analyze",
    response_model=ApplicationDetail,
    dependencies=[Depends(limit_write)],
)
async def analyze_application(
    application_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_service.get_application(db, current_user.id, application_id)
    await app_service.analyze_application(db, current_user, app, request=request)
    job = await _job(db, app.job_id)
    return await application_detail(db, app, job)


@router.post(
    "/{application_id}/fill",
    response_model=ApplicationDetail,
    dependencies=[Depends(limit_write)],
)
async def fill_application(
    application_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_service.get_application(db, current_user.id, application_id)
    await app_service.fill_application(db, current_user, app, request=request)
    job = await _job(db, app.job_id)
    return await application_detail(db, app, job)


@router.patch(
    "/{application_id}/answers/{answer_id}",
    response_model=AnswerOut,
    dependencies=[Depends(limit_write)],
)
async def update_answer(
    application_id: UUID,
    answer_id: UUID,
    payload: AnswerUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_service.get_application(db, current_user.id, application_id)
    answer = (
        await db.execute(
            select(ApplicationAnswer).where(
                ApplicationAnswer.id == answer_id,
                ApplicationAnswer.application_id == app.id,
            )
        )
    ).scalar_one_or_none()
    if answer is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    answer.field_value = payload.field_value
    answer.source = "user"
    answer.is_user_edited = True
    answer.validation_error = None
    await db.commit()
    await db.refresh(answer)
    return AnswerOut.model_validate(answer)


@router.post(
    "/{application_id}/approval/request",
    dependencies=[Depends(limit_write)],
)
async def request_approval(
    application_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_service.get_application(db, current_user.id, application_id)
    token, expires_at = await app_service.request_approval(db, current_user, app, request=request)
    job = await _job(db, app.job_id)
    preview = app.preview or {}
    return {
        "application_id": str(app.id),
        "approval_token": token,
        "expires_at": expires_at,
        "summary": {
            "job": {"title": job.title, "company": job.company, "url": job.application_url},
            "resume": preview.get("resume"),
            "answers": [
                {"label": answer.field_label, "value": answer.field_value}
                for answer in (
                    await db.execute(
                        select(ApplicationAnswer).where(ApplicationAnswer.application_id == app.id)
                    )
                ).scalars()
                if answer.field_value
            ],
            "warnings": preview.get("warnings") or [],
        },
    }


@router.post(
    "/{application_id}/approve",
    response_model=ApproveResponse,
    dependencies=[Depends(limit_write)],
)
async def approve_application(
    application_id: UUID,
    payload: ApproveRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_service.get_application(db, current_user.id, application_id)
    app, proof = await app_service.approve_application(
        db, current_user, app, payload.token, request=request
    )
    job = await _job(db, app.job_id)
    return ApproveResponse(
        application=application_out(
            app,
            {"id": str(job.id), "title": job.title, "company": job.company},
        ),
        proof=proof,
    )


@router.post(
    "/{application_id}/submit",
    response_model=SubmitResponse,
    dependencies=[Depends(limit_write)],
)
async def submit_application(
    application_id: UUID,
    payload: SubmitRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_service.get_application(db, current_user.id, application_id)
    if payload.proof.get("application_id") != str(app.id):
        raise HTTPException(status_code=403, detail="Approval proof does not match this application.")
    result = await app_service.submit_application(
        db, current_user, app, payload.proof, request=request
    )
    job = await _job(db, app.job_id)
    return SubmitResponse(
        application=application_out(
            app,
            {"id": str(job.id), "title": job.title, "company": job.company},
        ),
        outcome=result.get("outcome"),
        evidence=result.get("evidence"),
        validation_errors=result.get("validation_errors") or [],
    )


@router.post(
    "/{application_id}/reject",
    response_model=ApplicationOut,
    dependencies=[Depends(limit_write)],
)
async def reject_application(
    application_id: UUID,
    payload: RejectRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_service.get_application(db, current_user.id, application_id)
    app = await app_service.reject_application(db, current_user, app, payload.reason, request)
    job = await _job(db, app.job_id)
    return application_out(app, {"id": str(job.id), "title": job.title, "company": job.company})


@router.post(
    "/{application_id}/confirm-manual",
    response_model=ApplicationOut,
    dependencies=[Depends(limit_write)],
)
async def confirm_manual(
    application_id: UUID,
    payload: ManualConfirmRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_service.get_application(db, current_user.id, application_id)
    app = await app_service.mark_confirmed_manually(db, current_user, app, payload.evidence, request)
    job = await _job(db, app.job_id)
    return application_out(app, {"id": str(job.id), "title": job.title, "company": job.company})


@router.post(
    "/{application_id}/outcome",
    response_model=ApplicationOut,
    dependencies=[Depends(limit_write)],
)
async def record_outcome(
    application_id: UUID,
    payload: OutcomeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_service.get_application(db, current_user.id, application_id)
    app = await app_service.record_outcome(db, current_user, app, payload.outcome, payload.note, request)
    job = await _job(db, app.job_id)
    return application_out(app, {"id": str(job.id), "title": job.title, "company": job.company})


@router.get("/{application_id}/screenshot")
async def get_screenshot(
    application_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_service.get_application(db, current_user.id, application_id)
    key = app.screenshot_s3_key
    if not key:
        raise HTTPException(status_code=404, detail="No screenshot for this application yet")
    try:
        data = await storage.get(key)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return StreamingResponse(
        io.BytesIO(data),
        media_type="image/png",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/{application_id}/browser-frame")
async def application_browser_frame(
    application_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_service.get_application(db, current_user.id, application_id)
    session = (
        await db.execute(
            select(BrowserSession)
            .where(BrowserSession.application_id == app.id)
            .order_by(BrowserSession.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if session is None or not session.session_ref or session.status == "BLOCKED":
        raise HTTPException(status_code=404, detail="Live browser session is not available.")
    client = BrowserClient(base_url=session.worker_id)
    try:
        payload = await client.screenshot(session.session_ref)
    except BrowserWorkerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    data = decode_screenshot(payload.get("screenshot"))
    if not data:
        raise HTTPException(status_code=502, detail="Browser worker returned no screenshot.")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="image/png",
        headers={"Cache-Control": "private, no-store"},
    )

