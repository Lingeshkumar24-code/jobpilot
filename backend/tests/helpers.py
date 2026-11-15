"""Shared fixtures/helpers for backend tests. No network calls."""
from __future__ import annotations

import base64
import io
import uuid
from datetime import datetime, timezone

from docx import Document

from app.db.session import SessionLocal
from app.services.discovery import DiscoveryOutcome, ensure_sources
from app.models.core import Job, JobMatch

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def resume_docx() -> bytes:
    doc = Document()
    doc.add_paragraph("Jane Doe")
    doc.add_paragraph("jane.doe@example.com | +91 98765 43210 | Bengaluru, India")
    doc.add_paragraph("LinkedIn: https://www.linkedin.com/in/janedoe")
    doc.add_paragraph("Professional Summary")
    doc.add_paragraph("Backend engineer with 3 years of experience building APIs and data services.")
    doc.add_paragraph("Skills")
    doc.add_paragraph("Python, FastAPI, PostgreSQL, Docker, AWS, Git")
    doc.add_paragraph("Experience")
    doc.add_paragraph("Software Engineer | Acme Corp | 2022 - 2025")
    doc.add_paragraph("Built REST APIs and data pipelines with Python and PostgreSQL.")
    doc.add_paragraph("Education")
    doc.add_paragraph("B.Tech in Computer Science | Example University | 2022")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


async def upload_resume(client) -> dict:
    response = await client.post(
        "/api/v1/resumes/upload?use_llm=false",
        files={
            "file": (
                "jane_doe_resume.docx",
                resume_docx(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def seed_job(
    *,
    title: str = "Python Backend Engineer",
    company: str = "Acme",
    location: str = "Bengaluru, India",
    work_mode: str = "onsite",
) -> tuple[str, str]:
    async with SessionLocal() as db:
        sources = await ensure_sources(db)
        source = sources["remoteok"]
        job = Job(
            source_id=source.id,
            external_id=uuid.uuid4().hex,
            title=title,
            company=company,
            location=location,
            work_mode=work_mode,
            employment_type="full_time",
            description="Build Python FastAPI services with PostgreSQL and Docker.",
            application_url="https://example.com/jobs/" + uuid.uuid4().hex,
            source_url="https://example.com/jobs/" + uuid.uuid4().hex,
            posted_at=datetime.now(timezone.utc),
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
            last_verified_at=datetime.now(timezone.utc),
            is_active=True,
            dedup_key=uuid.uuid4().hex,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return str(job.id), str(source.id)


async def seed_match(user_id: str, job_id: str, score: float = 82.0) -> str:
    async with SessionLocal() as db:
        match = JobMatch(
            user_id=uuid.UUID(str(user_id)),
            job_id=uuid.UUID(str(job_id)),
            match_score=score,
            match_explanation={
                "summary": "Strong skills overlap.",
                "components": {"skills": {"score": 90, "weight": 0.45}},
                "matched_skills": ["Python"],
                "missing_skills": [],
                "reasons": ["Title matches your target role."],
            },
            is_dismissed=False,
        )
        db.add(match)
        await db.commit()
        await db.refresh(match)
        return str(match.id)


class FakeBrowserClient:
    configured = True

    def __init__(self, submit_outcome: str = "CONFIRMED", validation_errors=None):
        self.submit_outcome = submit_outcome
        self.validation_errors = validation_errors or []
        self.calls: list[str] = []

    async def analyze(self, url, application_id, resume_bytes, resume_filename):
        self.calls.append("analyze")
        return {
            "session_id": "fake-session-" + uuid.uuid4().hex[:8],
            "final_url": url,
            "title": "Apply | Acme",
            "detected": {"has_captcha": False, "requires_login": False},
            "warnings": [],
            "screenshot": {"base64": base64.b64encode(PNG).decode()},
            "fields": [
                {
                    "ref": "full_name",
                    "name": "full_name",
                    "label": "Full name",
                    "type": "text",
                    "tag": "input",
                    "required": True,
                },
                {
                    "ref": "email",
                    "name": "email",
                    "label": "Email",
                    "type": "email",
                    "tag": "input",
                    "required": True,
                },
                {
                    "ref": "phone",
                    "name": "phone",
                    "label": "Phone",
                    "type": "tel",
                    "tag": "input",
                    "required": False,
                },
                {
                    "ref": "resume",
                    "name": "resume",
                    "label": "Resume",
                    "type": "file",
                    "tag": "input",
                    "required": True,
                },
                {
                    "ref": "cover_letter",
                    "name": "cover_letter",
                    "label": "Cover letter",
                    "type": "textarea",
                    "tag": "textarea",
                    "required": False,
                },
            ],
        }

    async def fill(self, session_id, values, upload_resume=True):
        self.calls.append("fill")
        return {
            "filled": list(values.keys()),
            "skipped": [],
            "validation_errors": self.validation_errors,
            "resume_attached": True,
            "screenshot": {"base64": base64.b64encode(PNG).decode()},
        }

    async def submit(self, session_id, application_id, proof):
        self.calls.append("submit")
        if self.submit_outcome == "CONFIRMED":
            return {
                "outcome": "CONFIRMED",
                "evidence": {"text": "Thank you for applying. Your application was received."},
                "final_url": "https://example.com/thanks",
                "screenshot": {"base64": base64.b64encode(PNG).decode()},
            }
        if self.submit_outcome == "UNKNOWN_SUBMISSION_STATUS":
            return {
                "outcome": "UNKNOWN_SUBMISSION_STATUS",
                "evidence": {"reason": "No confirmation text appeared."},
                "final_url": "https://example.com/apply",
            }
        return {
            "outcome": self.submit_outcome,
            "evidence": {"reason": "Rejected by the target site."},
            "final_url": "https://example.com/apply",
        }

    async def close(self, session_id):
        self.calls.append("close")


class FakeConnector:
    key = "remoteok"
    display_name = "RemoteOK"
    attribution = "Listings via RemoteOK"
    base_url = "https://remoteok.com"
    requires_credentials = False
    notes = "Test connector"

    def __init__(self, listings):
        self.listings = listings

    def is_configured(self):
        return True

    def not_configured_reason(self):
        return ""

    async def fetch(self, filters, limit, prefs=None):
        from app.services.job_sources import ConnectorResult

        return ConnectorResult(
            source_key=self.key,
            display_name=self.display_name,
            listings=self.listings,
            duration_ms=1,
        )


def discovery_with(job, match) -> DiscoveryOutcome:
    return DiscoveryOutcome(
        jobs=[(job, match)], sources=[], warnings=[], fetched=1, stored=1
    )
