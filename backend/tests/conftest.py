"""Test harness: real app, isolated SQLite database, local file storage."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

TEST_DIR = Path(tempfile.mkdtemp(prefix="jobpilot-tests-"))
DB_PATH = TEST_DIR / "jobpilot.db"
STORAGE_DIR = TEST_DIR / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
)
os.environ["JWT_SECRET"] = "test-jwt-secret-not-for-production"
os.environ["APPROVAL_SIGNING_SECRET"] = "test-approval-secret-not-for-production"
os.environ["BROWSER_WORKER_SECRET"] = "test-worker-secret"
os.environ["N8N_WEBHOOK_SECRET"] = "test-n8n-secret"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["LOCAL_STORAGE_DIR"] = str(STORAGE_DIR)
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["ENVIRONMENT"] = "development"
os.environ["GEMINI_API_KEY"] = ""
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["FIRECRAWL_API_KEY"] = ""
os.environ["OLLAMA_BASE_URL"] = ""
os.environ["N8N_WEBHOOK_BASE_URL"] = ""

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.core import User  # noqa: E402

ORIGIN = "http://localhost:3000"


@pytest_asyncio.fixture
async def client():
    await engine.dispose()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Origin": ORIGIN},
            timeout=60.0,
        ) as test_client:
            yield test_client
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def auth_client(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "candidate@example.com", "password": "correct-horse-battery"},
    )
    assert response.status_code == 201, response.text
    return client


async def current_user_id() -> str:
    async with SessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.email == "candidate@example.com"))
        ).scalar_one()
        return str(user.id)


@pytest.fixture
def anyio_backend():
    return "asyncio"
