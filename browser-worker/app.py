"""
JobPilot AI browser worker API.

This service is intentionally separate from the FastAPI application: it holds
a Chromium process, may hold ephemeral form sessions, and must never receive
the primary database credentials. It only accepts authenticated calls from
the backend (shared secret header) and verifies a signed approval proof for
every submission.
"""
from __future__ import annotations

import base64
import asyncio
import hmac
import logging
import os
import contextlib
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
import httpx

from automation import BrowserAutomation, WorkerError

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("jobpilot.worker")

WORKER_SECRET = os.getenv("WORKER_SECRET", "")
WORKER_URL: str | None = None
ECS_TASK_ARN: str | None = None
_protection_task: asyncio.Task | None = None
automation = BrowserAutomation()


async def discover_worker_info() -> tuple[str | None, str | None]:
    """Return the task's direct address so later calls reach its live session."""
    configured = os.getenv("WORKER_ADVERTISE_URL")
    if configured:
        return configured.rstrip("/"), None
    metadata_url = os.getenv("ECS_CONTAINER_METADATA_URI_V4")
    if not metadata_url:
        return None, None
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{metadata_url.rstrip('/')}/task")
            response.raise_for_status()
            task = response.json()
        for container in task.get("Containers", []):
            for network in container.get("Networks", []):
                addresses = network.get("IPv4Addresses") or []
                if addresses:
                    return f"http://{addresses[0]}:8100", task.get("TaskARN")
    except Exception as exc:
        logger.warning("Could not resolve browser task address: %s", type(exc).__name__)
    return None, None


async def set_ecs_task_protection(enabled: bool) -> None:
    if not ECS_TASK_ARN or not os.getenv("ECS_CLUSTER_NAME"):
        return
    try:
        import boto3

        def update() -> None:
            client = boto3.client("ecs", region_name=os.getenv("AWS_REGION", "ap-south-1"))
            args = {
                "cluster": os.environ["ECS_CLUSTER_NAME"],
                "tasks": [ECS_TASK_ARN],
                "protectionEnabled": enabled,
            }
            if enabled:
                args["expiresInMinutes"] = 120
            client.update_task_protection(**args)

        await asyncio.to_thread(update)
    except Exception as exc:
        logger.warning("ECS task protection update failed: %s", type(exc).__name__)


async def _maintain_task_protection() -> None:
    while True:
        await asyncio.sleep(15 * 60)
        if automation.sessions:
            await set_ecs_task_protection(True)
        else:
            await set_ecs_task_protection(False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global WORKER_URL, ECS_TASK_ARN, _protection_task
    await automation.start()
    WORKER_URL, ECS_TASK_ARN = await discover_worker_info()
    _protection_task = asyncio.create_task(_maintain_task_protection())
    try:
        yield
    finally:
        if _protection_task:
            _protection_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await _protection_task
        await set_ecs_task_protection(False)
        _protection_task = None
        WORKER_URL = None
        ECS_TASK_ARN = None
        await automation.stop()


app = FastAPI(title="JobPilot AI - Browser Worker", version="1.0.0", lifespan=lifespan)


async def require_secret(x_worker_secret: str | None = Header(default=None)) -> None:
    if not WORKER_SECRET:
        raise HTTPException(status_code=503, detail="Worker secret is not configured.")
    if not x_worker_secret or not hmac.compare_digest(WORKER_SECRET, x_worker_secret):
        raise HTTPException(status_code=401, detail="Unauthorized worker request.")


class ResumePayload(BaseModel):
    filename: str = Field(max_length=500)
    content_base64: str


class AnalyzeRequest(BaseModel):
    url: str = Field(max_length=2000)
    application_id: str = Field(min_length=8, max_length=80)
    resume: ResumePayload | None = None


class FillRequest(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)
    upload_resume: bool = True


class ApprovalProof(BaseModel):
    application_id: str
    token_hash: str
    nonce: str
    expires_at: int
    signature: str


class SubmitRequest(BaseModel):
    application_id: str
    approval: ApprovalProof


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "browser-worker", "version": "1.0.0"}


@app.get("/v1/status", dependencies=[Depends(require_secret)])
async def status() -> dict[str, Any]:
    return await automation.stats()


@app.post("/v1/sessions/analyze", dependencies=[Depends(require_secret)])
async def analyze(payload: AnalyzeRequest) -> dict[str, Any]:
    resume = None
    filename = None
    if payload.resume:
        try:
            resume = base64.b64decode(payload.resume.content_base64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Resume payload is not valid base64.") from exc
        if len(resume) > 5 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Resume exceeds 5 MB.")
        filename = payload.resume.filename
    try:
        result = await automation.analyze(payload.url, payload.application_id, resume, filename)
        if WORKER_URL:
            result["worker_url"] = WORKER_URL
        if not result.get("detected", {}).get("has_captcha") and not result.get("detected", {}).get("requires_login"):
            await set_ecs_task_protection(True)
        return result
    except WorkerError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@app.post("/v1/sessions/{session_id}/fill", dependencies=[Depends(require_secret)])
async def fill(session_id: str, payload: FillRequest) -> dict[str, Any]:
    try:
        return await automation.fill(session_id, payload.values, payload.upload_resume)
    except WorkerError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@app.post("/v1/sessions/{session_id}/submit", dependencies=[Depends(require_secret)])
async def submit(session_id: str, payload: SubmitRequest) -> dict[str, Any]:
    try:
        return await automation.submit(
            session_id, payload.application_id, payload.approval.model_dump()
        )
    except WorkerError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@app.delete("/v1/sessions/{session_id}", dependencies=[Depends(require_secret)])
async def close(session_id: str) -> dict[str, str]:
    await automation.close(session_id)
    if not automation.sessions:
        await set_ecs_task_protection(False)
    return {"status": "closed"}
