"""End-to-end API tests against the real FastAPI app (SQLite test database)."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.core import Job, JobMatch
from app.services import applications as app_service
from app.services import discovery as discovery_module
from app.services.job_sources import JobListing
from app.services.job_sources.firecrawl import FirecrawlConnector, _build_query, _is_job_url, _title_company

from .conftest import current_user_id
from .helpers import (
    FakeBrowserClient,
    FakeConnector,
    discovery_with,
    seed_job,
    seed_match,
    upload_resume,
)

async def test_registration_cookie_session_and_csrf(auth_client):
    client = auth_client
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "candidate@example.com"
    assert client.cookies.get("jobpilot_session")

    origin = client.headers.pop("Origin")
    blocked = await client.post("/api/v1/profile", json={"full_name": "Jane Doe"})
    assert blocked.status_code == 403
    client.headers["Origin"] = origin

    updated = await client.patch("/api/v1/profile", json={"full_name": "Jane Doe"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["full_name"] == "Jane Doe"
    assert updated.json()["email"] == "candidate@example.com"

    wrong = await client.post(
        "/api/v1/auth/login",
        json={"email": "candidate@example.com", "password": "wrong-password"},
    )
    assert wrong.status_code == 401

    logout = await client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    after = await client.get("/api/v1/auth/me")
    assert after.status_code == 401


def test_firecrawl_builds_role_and_location_query():
    query = _build_query({
        "role": ["GenAI Engineer"],
        "location": ["Bengaluru"],
        "work_mode": ["remote"],
        "posted_within_days": 30,
    })
    assert "GenAI Engineer" in query
    assert "Bengaluru" in query
    assert "jobs careers apply" in query
    assert "remote" in query


def test_firecrawl_extracts_title_and_company_from_job_results():
    title, company = _title_company(
        "AI Engineer at Example Labs | Greenhouse",
        "https://boards.greenhouse.io/examplelabs/jobs/123",
    )
    assert title == "AI Engineer"
    assert company == "Example Labs"
    assert _is_job_url("https://boards.greenhouse.io/examplelabs/jobs/123")
    assert not _is_job_url("https://www.naukri.com/ai-engineer-jobs-in-bangalore-bengaluru")
    assert not _is_job_url("https://in.indeed.com/q-genai-l-bengaluru-jobs.html")
    assert _is_job_url("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIA/job/India-Bengaluru/GenAI-Engineer_JR12345")


async def test_firecrawl_skips_when_api_key_missing(monkeypatch):
    from app.services.job_sources import firecrawl as firecrawl_module

    monkeypatch.setattr(firecrawl_module.settings, "FIRECRAWL_API_KEY", None)
    result = await FirecrawlConnector().fetch({"role": ["Engineer"]}, 10)
    assert result.skipped_reason
    assert not result.listings


async def test_resume_upload_parse_and_download(auth_client):
    client = auth_client
    uploaded = await upload_resume(client)
    assert uploaded["file"]["status"] == "parsed"
    assert uploaded["version"]["extraction_method"] in {"heuristic", "rule_based", "llm+validated"}
    assert uploaded["completeness"] > 0

    profile = (await client.get("/api/v1/profile")).json()
    assert profile["full_name"] == "Jane Doe"
    assert profile["email"] == "jane.doe@example.com"
    assert "Python" in profile["skills"]

    listing = await client.get("/api/v1/resumes")
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    resume_id = listing.json()[0]["id"]

    download = await client.get(f"/api/v1/resumes/{resume_id}/download")
    assert download.status_code == 200
    assert download.content.startswith(b"PK\x03\x04")
    assert len(download.content) == uploaded["file"]["size_bytes"]

    bad = await client.post(
        "/api/v1/resumes/upload",
        files={"file": ("resume.pdf", b"this is not a pdf", "application/pdf")},
    )
    assert bad.status_code == 415


async def test_search_uses_real_filters_and_explainable_scores(auth_client, monkeypatch):
    client = auth_client
    await upload_resume(client)

    listing = JobListing(
        source_key="remoteok",
        external_id="job-1",
        title="Python Backend Engineer",
        company="Acme",
        location="Bengaluru, India",
        description="Python FastAPI PostgreSQL Docker REST APIs",
        application_url="https://remoteok.com/remote-jobs/1",
        work_mode="onsite",
        employment_type="full_time",
        posted_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        discovery_module,
        "CONNECTORS",
        {"remoteok": FakeConnector([listing])},
    )

    response = await client.post(
        "/api/v1/search/execute",
        json={"query": "python backend engineer jobs in bangalore", "limit": 10},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["filters"]["role"] == ["Python Backend Engineer"]
    assert body["filters"]["location"] == ["Bengaluru"]
    assert body["total"] >= 1
    job = body["jobs"][0]
    assert job["title"] == "Python Backend Engineer"
    assert job["match_score"] is not None
    assert job["match_explanation"]["weights_used"]["skills"] > 0
    assert job["match_explanation"]["matched_skills"]
    assert body["sources"][0]["key"] == "remoteok"
    assert body["sources"][0]["status"] == "ok"


def test_role_filter_uses_job_title_not_description_text():
    assert discovery_module._role_matches(
        "Entry Level GenAI Engineer", "Junior GenAI Engineer"
    )
    assert not discovery_module._role_matches(
        "Entry Level GenAI Engineer", "Senior Product Manager"
    )
    assert discovery_module._role_matches("AI Engineer", "Artificial Intelligence Engineer")


async def test_application_cannot_submit_without_approval(auth_client, monkeypatch):
    client = auth_client
    await upload_resume(client)
    job_id, _ = await seed_job()
    fake = FakeBrowserClient()
    monkeypatch.setattr(app_service, "browser_client", fake)

    created = await client.post("/api/v1/applications", json={"job_id": job_id})
    assert created.status_code == 201, created.text
    app_id = created.json()["id"]

    analyzed = await client.post(f"/api/v1/applications/{app_id}/analyze")
    assert analyzed.status_code == 200, analyzed.text
    assert analyzed.json()["status"] == "FORM_ANALYZED"
    assert analyzed.json()["answers"]

    filled = await client.post(f"/api/v1/applications/{app_id}/fill")
    assert filled.status_code == 200, filled.text
    assert filled.json()["status"] == "VERIFICATION_PENDING"
    assert filled.json()["preview"]["verification"]["ok"] is True

    early = await client.post(
        f"/api/v1/applications/{app_id}/submit",
        json={"proof": {"application_id": app_id}},
    )
    assert early.status_code == 409

    requested = await client.post(f"/api/v1/applications/{app_id}/approval/request")
    assert requested.status_code == 200, requested.text
    token = requested.json()["approval_token"]

    wrong = await client.post(
        f"/api/v1/applications/{app_id}/approve", json={"token": "x" * 40}
    )
    assert wrong.status_code == 403

    approved = await client.post(
        f"/api/v1/applications/{app_id}/approve", json={"token": token}
    )
    assert approved.status_code == 200, approved.text
    proof = approved.json()["proof"]

    submitted = await client.post(
        f"/api/v1/applications/{app_id}/submit", json={"proof": proof}
    )
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["outcome"] == "CONFIRMED"
    assert body["application"]["status"] == "CONFIRMED"

    duplicate = await client.post(
        f"/api/v1/applications/{app_id}/submit", json={"proof": proof}
    )
    assert duplicate.status_code == 409

    events = await client.get(f"/api/v1/applications/{app_id}/events")
    assert events.status_code == 200
    assert any(event["to_status"] == "CONFIRMED" for event in events.json())


async def test_unknown_submission_is_never_reported_confirmed(auth_client, monkeypatch):
    client = auth_client
    await upload_resume(client)
    job_id, _ = await seed_job(title="Data Engineer", company="Beta")
    fake = FakeBrowserClient(submit_outcome="UNKNOWN_SUBMISSION_STATUS")
    monkeypatch.setattr(app_service, "browser_client", fake)

    app_id = (
        await client.post("/api/v1/applications", json={"job_id": job_id})
    ).json()["id"]
    assert (await client.post(f"/api/v1/applications/{app_id}/analyze")).status_code == 200
    assert (await client.post(f"/api/v1/applications/{app_id}/fill")).status_code == 200
    token = (
        await client.post(f"/api/v1/applications/{app_id}/approval/request")
    ).json()["approval_token"]
    proof = (
        await client.post(
            f"/api/v1/applications/{app_id}/approve", json={"token": token}
        )
    ).json()["proof"]

    result = await client.post(
        f"/api/v1/applications/{app_id}/submit", json={"proof": proof}
    )
    assert result.status_code == 200, result.text
    assert result.json()["outcome"] == "UNKNOWN_SUBMISSION_STATUS"
    assert result.json()["application"]["status"] == "UNKNOWN_SUBMISSION_STATUS"

    manual = await client.post(
        f"/api/v1/applications/{app_id}/confirm-manual",
        json={"evidence": "The employer portal shows my application was received."},
    )
    assert manual.status_code == 200
    assert manual.json()["status"] == "CONFIRMED"


async def test_agent_pauses_for_human_approval_then_submits(auth_client, monkeypatch):
    client = auth_client
    await upload_resume(client)
    job_id, _ = await seed_job(title="AI Engineer", company="Gamma")
    user_id = await current_user_id()
    await seed_match(user_id, job_id, score=88.0)

    async with SessionLocal() as db:
        job = (
            await db.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
        ).scalar_one()
        match = (
            await db.execute(
                select(JobMatch).where(JobMatch.job_id == uuid.UUID(job_id))
            )
        ).scalar_one()

    async def fake_discover(*args, **kwargs):
        return discovery_with(job, match)

    from app.agents import graph as graph_module

    monkeypatch.setattr(graph_module, "discover", fake_discover)
    fake = FakeBrowserClient()
    monkeypatch.setattr(app_service, "browser_client", fake)

    started = await client.post(
        "/api/v1/agents/runs",
        json={
            "goal": "find an AI engineer job and prepare an application",
            "prepare_applications": True,
            "limit": 3,
        },
    )
    assert started.status_code == 201, started.text
    run = started.json()
    assert run["status"] == "awaiting_approval"
    assert run["interrupt_payload"]["application_id"]
    application_id = run["interrupt_payload"]["application_id"]
    assert run["interrupt_payload"]["job"]["title"] == "AI Engineer"

    no_proof = await client.post(
        f"/api/v1/agents/runs/{run['id']}/resume",
        json={"approved": True, "application_id": application_id},
    )
    assert no_proof.status_code == 400

    token = (
        await client.post(f"/api/v1/applications/{application_id}/approval/request")
    ).json()["approval_token"]
    proof = (
        await client.post(
            f"/api/v1/applications/{application_id}/approve", json={"token": token}
        )
    ).json()["proof"]

    resumed = await client.post(
        f"/api/v1/agents/runs/{run['id']}/resume",
        json={"approved": True, "application_id": application_id, "proof": proof},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "completed"
    assert resumed.json()["result"]["submission_outcome"] == "CONFIRMED"

    application = await client.get(f"/api/v1/applications/{application_id}")
    assert application.json()["status"] == "CONFIRMED"


async def test_n8n_webhook_signature_and_idempotency(auth_client):
    client = auth_client
    body = json.dumps({"workflow": "daily_digest"}).encode()
    bad = await client.post(
        "/api/v1/automation/webhooks/daily_digest",
        content=body,
        headers={"Content-Type": "application/json", "X-JobPilot-Signature": "sha256=bad"},
    )
    assert bad.status_code == 401

    signature = "sha256=" + hmac.new(
        b"test-n8n-secret", body, hashlib.sha256
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-JobPilot-Signature": signature,
        "X-JobPilot-Delivery": "delivery-1",
    }
    first = await client.post(
        "/api/v1/automation/webhooks/daily_digest", content=body, headers=headers
    )
    assert first.status_code == 200, first.text
    assert first.json()["accepted"] is True

    duplicate = await client.post(
        "/api/v1/automation/webhooks/daily_digest", content=body, headers=headers
    )
    assert duplicate.status_code == 200
    assert "Duplicate" in duplicate.json()["message"]

    workflows = await client.get("/api/v1/automation/workflows")
    assert workflows.status_code == 200
    assert {row["key"] for row in workflows.json()} >= {
        "daily_digest",
        "refresh_jobs",
        "followup_reminder",
        "resume_processing",
        "new_job_notification",
        "application_tracking",
        "failure_handling",
    }

    failure_body = json.dumps({"workflow": "failure_handling", "source_workflow": "unit", "execution_id": "42", "error": "expected test failure"}).encode()
    failure_sig = "sha256=" + hmac.new(b"test-n8n-secret", failure_body, hashlib.sha256).hexdigest()
    failure = await client.post(
        "/api/v1/automation/webhooks/failure_handling",
        content=failure_body,
        headers={"Content-Type": "application/json", "X-JobPilot-Signature": failure_sig, "X-JobPilot-Delivery": "failure-42"},
    )
    assert failure.status_code == 200, failure.text
    assert "recorded" in failure.json()["message"]

    resume_body = json.dumps({"workflow": "resume_processing", "resume_id": "resume-1", "user_id": "00000000-0000-4000-8000-000000000001"}).encode()
    resume_sig = "sha256=" + hmac.new(b"test-n8n-secret", resume_body, hashlib.sha256).hexdigest()
    resume = await client.post(
        "/api/v1/automation/webhooks/resume_processing",
        content=resume_body,
        headers={"Content-Type": "application/json", "X-JobPilot-Signature": resume_sig},
    )
    assert resume.status_code == 501


async def test_system_status_reports_real_configuration(auth_client):
    client = auth_client
    response = await client.get("/api/v1/settings/system")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["database"] == "ok"
    assert body["storage_backend"] == "local"
    assert body["llm_provider"] in {"rule_based", "openrouter", "gemini", "ollama"}
    assert body["sources"]
    assert body["counts"]["jobs"] == 0
