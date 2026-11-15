"""
JobPilot AI — FastAPI entrypoint.

Routers that exist here are wired to real services. Nothing is a static mock:
job listings come from live public feeds, resumes are parsed from uploaded
bytes, and submissions require an explicit per-application approval.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import AsyncExitStack, asynccontextmanager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1 import (
    agents,
    applications,
    auth,
    browser,
    automation,
    jobs,
    matches,
    profile,
    resumes,
    search,
    settings as settings_router,
)
from app.core.config import settings
from app.core.middleware import OriginCheckMiddleware, SecurityHeadersMiddleware
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as resources:
        # Agent approval interrupts must survive API restarts and ECS task
        # replacement. PostgreSQL is already the production database; use a
        # dedicated LangGraph checkpoint schema in that same durable service.
        if settings.DATABASE_URL.startswith(("postgresql+asyncpg://", "postgresql://", "postgres://")):
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from app.agents.graph import configure_checkpointer

            checkpoint_url = settings.DATABASE_URL.replace(
                "postgresql+asyncpg://", "postgresql://", 1
            )
            checkpointer = await resources.enter_async_context(
                AsyncPostgresSaver.from_conn_string(checkpoint_url)
            )
            await checkpointer.setup()
            configure_checkpointer(checkpointer)
        # Seed catalogue rows that are safe to create repeatedly. Failures here
        # (for example, a database that has not been migrated yet) are logged
        # and do not hide the real error from the first request.
        try:
            from app.api.v1.automation import seed_workflows
            from app.services.discovery import ensure_sources

            async with SessionLocal() as db:
                await ensure_sources(db)
                await seed_workflows(db)
                await db.commit()
        except Exception as exc:  # pragma: no cover - startup diagnostics
            logger.warning("Startup seed skipped: %s", type(exc).__name__)
        yield


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description=(
        "AI-powered job discovery, explainable matching, resume intelligence, and "
        "human-approved application assistance. No CAPTCHA bypass, no scrapers for "
        "credential-gated boards, and no submission without a one-time proof."
    ),
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(OriginCheckMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


@app.get("/health", tags=["system"])
async def health():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
    }


@app.get("/health/ready", tags=["system"])
async def readiness():
    database = "ok"
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception:
        database = "error"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "environment": settings.ENVIRONMENT,
    }


@app.get("/", tags=["system"])
async def root():
    return {
        "message": "JobPilot AI API — see /docs for the OpenAPI schema.",
        "version": "1.0.0",
        "human_approval_required": True,
    }


app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(profile.router, prefix="/api/v1/profile", tags=["profile"])
app.include_router(resumes.router, prefix="/api/v1/resumes", tags=["resumes"])
app.include_router(search.router, prefix="/api/v1/search", tags=["search"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["jobs"])
app.include_router(matches.router, prefix="/api/v1/matches", tags=["matches"])
app.include_router(applications.router, prefix="/api/v1/applications", tags=["applications"])
app.include_router(browser.router, prefix="/api/v1/browser", tags=["browser"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["agents"])
app.include_router(automation.router, prefix="/api/v1/automation", tags=["automation"])
app.include_router(settings_router.router, prefix="/api/v1/settings", tags=["settings"])
