"""
Application lifecycle service.

This module owns every legal status change and every guard around it:
  * one application per (user, job);
  * explicit per-application approval tokens (hashed at rest);
  * one-time submission proof signed for the browser worker;
  * confirmation only from evidence returned by the target site;
  * audit events for every transition.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import ALLOWED_TRANSITIONS
from app.core.security import hash_token, sign_approval_proof
from app.models.core import (
    Application,
    ApplicationAnswer,
    ApplicationEvent,
    Approval,
    BrowserSession,
    CandidateProfile,
    Job,
    JobSkill,
    ResumeFile,
    ResumeVersion,
    User,
)
from app.services import audit
from app.services.browser_client import (
    BrowserClient,
    BrowserWorkerError,
    browser_client,
    decode_screenshot,
    screenshot_key,
)
from app.services.storage import StorageError, storage

SENSITIVE_FIELD_MARKERS = (
    "gender",
    "sex",
    "race",
    "ethnic",
    "veteran",
    "disability",
    "religion",
    "caste",
    "marital",
    "social security",
    "ssn",
    "aadhaar",
    "passport",
    "date of birth",
    "dob",
    "nationality",
)

COVER_LETTER_MARKERS = ("cover letter", "why do you", "why are you", "motivation", "message to")
CONSENT_MARKERS = ("agree", "consent", "privacy", "terms", "certify")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _as_uuid(value, label: str = "Resource"):
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=f"{label} not found") from exc


async def get_application(db: AsyncSession, user_id, application_id) -> Application:
    application_id = _as_uuid(application_id, "Application")
    app = (
        await db.execute(
            select(Application).where(
                Application.id == application_id,
                Application.user_id == user_id,
                Application.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


async def get_job(db: AsyncSession, job_id) -> Job:
    job_id = _as_uuid(job_id, "Job")
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def create_application(
    db: AsyncSession,
    user: User,
    job_id,
    resume_version_id=None,
    request: Request | None = None,
) -> Application:
    job = await get_job(db, job_id)
    if resume_version_id is not None:
        resume_version_id = _as_uuid(resume_version_id, "Resume version")
        version = (
            await db.execute(
                select(ResumeVersion).where(
                    ResumeVersion.id == resume_version_id, ResumeVersion.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if version is None:
            raise HTTPException(status_code=404, detail="Resume version not found")
    dedupe = f"{user.id}:{job.id}"
    existing = (
        await db.execute(select(Application).where(Application.dedupe_key == dedupe))
    ).scalar_one_or_none()
    if existing and existing.status not in {"CANCELLED", "FAILED"}:
        raise HTTPException(
            status_code=409,
            detail={"message": "An application for this job already exists.", "application_id": str(existing.id)},
        )

    if existing is not None:
        # A previously cancelled/failed record can be retried; the unique
        # (user, job) key is reset on the same row rather than duplicated.
        app = existing
        app.status = "DISCOVERED"
        app.resume_version_id = resume_version_id
        app.preview = {
            "job": {
                "id": str(job.id),
                "title": job.title,
                "company": job.company,
                "application_url": job.application_url,
                "source": job.source_url,
            }
        }
        app.failure_reason = None
        app.outcome = None
        app.confirmation_evidence = None
        app.approved_at = None
        app.submitted_at = None
        app.confirmed_at = None
        app.submission_attempts = 0
    else:
        app = Application(
            user_id=user.id,
            job_id=job.id,
            resume_version_id=resume_version_id,
            status="DISCOVERED",
            dedupe_key=dedupe,
            preview={
                "job": {
                    "id": str(job.id),
                    "title": job.title,
                    "company": job.company,
                    "application_url": job.application_url,
                    "source": job.source_url,
                }
            },
        )
        db.add(app)
    await db.flush()
    await _event(db, app, "application_created", actor="user", payload={"job_id": str(job.id)})
    await audit.record(
        db,
        user_id=user.id,
        action="application.created",
        resource_type="application",
        resource_id=app.id,
        details={"job_id": str(job.id)},
        request=request,
    )
    await db.commit()
    await db.refresh(app)
    return app


async def transition(
    db: AsyncSession,
    app: Application,
    to_status: str,
    *,
    actor: str = "system",
    payload: dict | None = None,
    commit: bool = False,
) -> Application:
    from_status = app.status
    if to_status == from_status:
        return app
    if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Illegal application transition: {from_status} → {to_status}",
        )
    app.status = to_status
    now = datetime.now(timezone.utc)
    if to_status == "APPROVED":
        app.approved_at = now
    elif to_status == "SUBMITTED":
        app.submitted_at = now
    elif to_status == "CONFIRMED":
        app.confirmed_at = now
    await _event(db, app, f"status_{to_status.lower()}", actor=actor, from_status=from_status, to_status=to_status, payload=payload)
    if commit:
        await db.commit()
        await db.refresh(app)
    else:
        await db.flush()
    return app


async def _event(
    db: AsyncSession,
    app: Application,
    event_type: str,
    *,
    actor: str = "system",
    from_status: str | None = None,
    to_status: str | None = None,
    payload: dict | None = None,
) -> None:
    db.add(
        ApplicationEvent(
            application_id=app.id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            payload=payload,
        )
    )


# --------------------------------------------------------------------------
# Resume selection
# --------------------------------------------------------------------------

async def select_resume(
    db: AsyncSession, user: User, app: Application
) -> tuple[ResumeVersion, ResumeFile]:
    version = None
    if app.resume_version_id:
        version = (
            await db.execute(
                select(ResumeVersion).where(
                    ResumeVersion.id == app.resume_version_id, ResumeVersion.user_id == user.id
                )
            )
        ).scalar_one_or_none()
    if version is None:
        version = (
            await db.execute(
                select(ResumeVersion)
                .join(ResumeFile, ResumeFile.id == ResumeVersion.resume_file_id)
                .where(
                    ResumeVersion.user_id == user.id,
                    ResumeVersion.is_active.is_(True),
                    ResumeVersion.deleted_at.is_(None),
                    ResumeFile.deleted_at.is_(None),
                )
                .order_by(ResumeVersion.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if version is None:
        raise HTTPException(
            status_code=409,
            detail="Upload a resume before preparing an application.",
        )
    resume_file = (
        await db.execute(select(ResumeFile).where(ResumeFile.id == version.resume_file_id))
    ).scalar_one_or_none()
    if resume_file is None:
        raise HTTPException(status_code=409, detail="The selected resume file no longer exists.")
    return version, resume_file


async def _resume_bytes(resume_file: ResumeFile) -> bytes:
    try:
        return await storage.get(resume_file.s3_key)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# --------------------------------------------------------------------------
# Analyze / fill / verify
# --------------------------------------------------------------------------

async def analyze_application(
    db: AsyncSession,
    user: User,
    app: Application,
    *,
    client: BrowserClient | None = None,
    request: Request | None = None,
) -> dict:
    client = client or browser_client
    if app.status not in {"DISCOVERED", "MATCHED", "APPLICATION_OPENED", "NEEDS_USER_INPUT", "FORM_ANALYZED", "FORM_FILLED", "VERIFICATION_PENDING"}:
        raise HTTPException(
            status_code=409, detail=f"Cannot analyze an application in status {app.status}."
        )
    previous_session = await _active_session(db, app)
    if previous_session is not None:
        previous_client = BrowserClient(base_url=previous_session.worker_id or settings.BROWSER_WORKER_URL)
        await previous_client.close(previous_session.session_ref)
        previous_session.status = "CLOSED"
        await db.flush()
    job = await get_job(db, app.job_id)
    version, resume_file = await select_resume(db, user, app)
    if app.resume_version_id != version.id:
        app.resume_version_id = version.id
    resume_bytes = await _resume_bytes(resume_file)

    if app.status in {"FORM_FILLED", "VERIFICATION_PENDING"}:
        await transition(db, app, "NEEDS_USER_INPUT", actor="user", payload={"reason": "Form inspection was requested again."})

    if app.status in {"DISCOVERED", "MATCHED"}:
        await transition(db, app, "APPLICATION_OPENED", actor="browser")
    try:
        analysis = await client.analyze(
            job.application_url,
            str(app.id),
            resume_bytes,
            resume_file.original_filename,
        )
    except BrowserWorkerError as exc:
        await _event(db, app, "browser_analyze_failed", actor="browser", payload={"error": str(exc)})
        await db.commit()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    screenshot = decode_screenshot(analysis.get("screenshot"))
    key = None
    if screenshot:
        key = screenshot_key(str(user.id), str(app.id), "analyze")
        await storage.put(key, screenshot, "image/png")

    session = BrowserSession(
        application_id=app.id,
        worker_id=analysis.get("worker_url") or settings.BROWSER_WORKER_URL,
        session_ref=analysis["session_id"],
        status="ANALYZED",
        last_url=analysis.get("final_url") or job.application_url,
        screenshot_s3_key=key,
        metadata_json={
            "title": analysis.get("title"),
            "detected": analysis.get("detected"),
            "captcha": analysis.get("detected", {}).get("has_captcha"),
            "login": analysis.get("detected", {}).get("requires_login"),
        },
    )
    db.add(session)

    profile = (
        await db.execute(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    ).scalar_one_or_none()
    job_skills = list(
        (
            await db.execute(select(JobSkill.skill).where(JobSkill.job_id == job.id))
        ).scalars()
    )
    answers, missing, warnings = prepare_answers(
        analysis.get("fields") or [], profile, version.parsed_json or {}, job, job_skills
    )
    await _replace_answers(db, app, answers)

    app.screenshot_s3_key = key
    app.preview = {
        **(app.preview or {}),
        "job": {
            "id": str(job.id),
            "title": job.title,
            "company": job.company,
            "application_url": job.application_url,
            "source": job.source_url,
        },
        "resume": {
            "id": str(version.id),
            "filename": resume_file.original_filename,
            "version_number": version.version_number,
        },
        "fields": analysis.get("fields") or [],
        "application_form_detected": bool((analysis.get("detected") or {}).get("has_application_form")),
        "answers": answers,
        "missing_required": missing,
        "warnings": (analysis.get("warnings") or []) + warnings,
        "worker_session_id": analysis["session_id"],
        "final_url": analysis.get("final_url"),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }

    if analysis.get("detected", {}).get("has_captcha"):
        await transition(db, app, "CAPTCHA_REQUIRED", actor="browser", payload={"url": job.application_url})
    elif analysis.get("detected", {}).get("requires_login"):
        await transition(db, app, "LOGIN_REQUIRED", actor="browser", payload={"url": job.application_url})
    elif (analysis.get("detected") or {}).get("has_application_form"):
        await transition(db, app, "FORM_ANALYZED", actor="browser")
    else:
        await transition(
            db,
            app,
            "NEEDS_USER_INPUT",
            actor="browser",
            payload={"reason": "No employer application form was found at this job listing."},
        )

    if analysis.get("detected", {}).get("has_captcha") or analysis.get("detected", {}).get("requires_login"):
        session.status = "BLOCKED"
        await (client or BrowserClient(base_url=session.worker_id)).close(session.session_ref)

    await audit.record(
        db,
        user_id=user.id,
        action="application.analyzed",
        resource_type="application",
        resource_id=app.id,
        details={"fields": len(analysis.get("fields") or []), "missing_required": missing},
        request=request,
    )
    await db.commit()
    await db.refresh(app)
    return {"application": app, "analysis": analysis, "missing_required": missing}


async def fill_application(
    db: AsyncSession,
    user: User,
    app: Application,
    *,
    client: BrowserClient | None = None,
    request: Request | None = None,
) -> dict:
    if app.status not in {"FORM_ANALYZED", "NEEDS_USER_INPUT"}:
        raise HTTPException(status_code=409, detail=f"Cannot fill an application in status {app.status}.")
    session = await _active_session(db, app)
    if session is None:
        raise HTTPException(status_code=409, detail="Browser session expired. Inspect the form again.")
    client = client or (browser_client if type(browser_client) is not BrowserClient else BrowserClient(base_url=session.worker_id or settings.BROWSER_WORKER_URL))
    answers = await _answers(db, app)
    missing = [
        a.field_label or a.field_name
        for a in answers
        if a.is_required and a.field_type not in {"file", "checkbox", "radio"} and not a.field_value
    ]
    if missing:
        await transition(db, app, "NEEDS_USER_INPUT", actor="system", payload={"missing_required": missing})
        await db.commit()
        raise HTTPException(
            status_code=409,
            detail={"message": "Required fields need your input.", "missing_required": missing},
        )

    values = {a.field_name: a.field_value or "" for a in answers if a.field_value}
    try:
        result = await client.fill(session.session_ref, values, upload_resume=True)
    except BrowserWorkerError as exc:
        await _event(db, app, "browser_fill_failed", actor="browser", payload={"error": str(exc)})
        await db.commit()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    screenshot = decode_screenshot(result.get("screenshot"))
    if screenshot:
        key = screenshot_key(str(user.id), str(app.id), "filled")
        await storage.put(key, screenshot, "image/png")
        app.screenshot_s3_key = key
        session.screenshot_s3_key = key

    session.status = "FILLED"
    validation_errors = result.get("validation_errors") or []
    app.preview = {
        **(app.preview or {}),
        "filled": result.get("filled") or [],
        "skipped": result.get("skipped") or [],
        "validation_errors": validation_errors,
        "resume_attached": result.get("resume_attached"),
        "filled_at": datetime.now(timezone.utc).isoformat(),
    }
    await transition(db, app, "FORM_FILLED", actor="browser")
    if validation_errors:
        await transition(
            db,
            app,
            "NEEDS_USER_INPUT",
            actor="browser",
            payload={"validation_errors": validation_errors},
        )
        await db.commit()
        raise HTTPException(
            status_code=409,
            detail={"message": "The site rejected some values.", "validation_errors": validation_errors},
        )

    verification = await verify_application_internal(db, app, answers, result)
    if not verification.get("ok"):
        # Unresolved required fields (including an unchecked consent box) must
        # send the application back to the user, not to approval.
        await transition(
            db,
            app,
            "NEEDS_USER_INPUT",
            actor="system",
            payload={"verification": verification},
        )
        await db.commit()
        await db.refresh(app)
        raise HTTPException(
            status_code=409,
            detail={
                "message": "The form still needs your input before approval.",
                "verification": verification,
            },
        )
    await transition(db, app, "VERIFICATION_PENDING", actor="system", payload=verification)
    await audit.record(
        db,
        user_id=user.id,
        action="application.filled",
        resource_type="application",
        resource_id=app.id,
        details={"fields": len(values), "verification": verification},
        request=request,
    )
    await db.commit()
    await db.refresh(app)
    return {"application": app, "fill": result, "verification": verification}


async def verify_application_internal(
    db: AsyncSession, app: Application, answers: list[ApplicationAnswer], fill_result: dict
) -> dict:
    missing = [
        a.field_label or a.field_name
        for a in answers
        if a.is_required and a.field_type not in {"file"} and not a.field_value
    ]
    file_fields = [
        a for a in answers if a.field_type == "file" and a.is_required
    ]
    resume_ok = not file_fields or bool(fill_result.get("resume_attached"))
    validation_errors = fill_result.get("validation_errors") or []
    ok = not missing and resume_ok and not validation_errors
    result = {
        "ok": ok,
        "missing_required": missing,
        "resume_attached": resume_ok,
        "validation_errors": validation_errors,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    app.preview = {**(app.preview or {}), "verification": result}
    return result


async def request_approval(
    db: AsyncSession,
    user: User,
    app: Application,
    *,
    request: Request | None = None,
) -> tuple[str, datetime]:
    if app.status not in {"VERIFICATION_PENDING", "FORM_FILLED"}:
        raise HTTPException(
            status_code=409,
            detail=f"Approval can only be requested after verification (current: {app.status}).",
        )
    session = await _active_session(db, app)
    if session is None:
        raise HTTPException(status_code=409, detail="Browser session has expired. Re-analyze the form.")
    verification = (app.preview or {}).get("verification") or {}
    if verification and not verification.get("ok", False):
        raise HTTPException(
            status_code=409,
            detail={"message": "Verification has unresolved issues.", "verification": verification},
        )

    # Revoke any earlier pending approval for this application.
    existing = (
        await db.execute(select(Approval).where(Approval.application_id == app.id))
    ).scalar_one_or_none()
    raw = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.APPROVAL_TOKEN_TTL_MINUTES)
    if existing:
        existing.token_hash = hash_token(raw)
        existing.approved_by = user.id
        existing.expires_at = expires_at
        existing.used_at = None
        existing.revoked_at = None
        existing.payload = {"issued_at": datetime.now(timezone.utc).isoformat()}
        approval = existing
    else:
        approval = Approval(
            application_id=app.id,
            token_hash=hash_token(raw),
            approved_by=user.id,
            expires_at=expires_at,
            payload={"issued_at": datetime.now(timezone.utc).isoformat()},
        )
        db.add(approval)
    await db.flush()

    if app.status == "FORM_FILLED":
        await transition(db, app, "VERIFICATION_PENDING", actor="system")
    await transition(db, app, "USER_APPROVAL_PENDING", actor="user")
    app.preview = {
        **(app.preview or {}),
        "approval_requested_at": datetime.now(timezone.utc).isoformat(),
        "approval_expires_at": expires_at.isoformat(),
    }
    await audit.record(
        db,
        user_id=user.id,
        action="application.approval_requested",
        resource_type="application",
        resource_id=app.id,
        details={"expires_at": expires_at.isoformat()},
        request=request,
    )
    await db.commit()
    return raw, expires_at


async def approve_application(
    db: AsyncSession,
    user: User,
    app: Application,
    raw_token: str,
    *,
    request: Request | None = None,
) -> tuple[Application, dict]:
    if app.status != "USER_APPROVAL_PENDING":
        raise HTTPException(status_code=409, detail=f"No approval is pending (current: {app.status}).")
    approval = (
        await db.execute(select(Approval).where(Approval.application_id == app.id))
    ).scalar_one_or_none()
    if approval is None:
        raise HTTPException(status_code=409, detail="No approval record exists. Request approval again.")
    if approval.approved_by != user.id:
        raise HTTPException(status_code=403, detail="This approval belongs to another user.")
    if approval.revoked_at is not None:
        raise HTTPException(status_code=409, detail="This approval has been revoked.")
    if approval.used_at is not None:
        raise HTTPException(status_code=409, detail="This approval has already been used.")
    if _as_utc(approval.expires_at) < datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="This approval has expired. Request a new one.")
    if not secrets.compare_digest(approval.token_hash, hash_token(raw_token)):
        raise HTTPException(status_code=403, detail="Approval token is invalid.")

    app.approved_by = user.id
    await transition(db, app, "APPROVED", actor="user")
    await audit.record(
        db,
        user_id=user.id,
        action="application.approved",
        resource_type="application",
        resource_id=app.id,
        details={"job_id": str(app.job_id)},
        request=request,
    )
    await db.commit()
    await db.refresh(app)

    nonce = secrets.token_hex(16)
    expires_utc = _as_utc(approval.expires_at)
    expires_at = int(expires_utc.timestamp())
    proof = {
        "application_id": str(app.id),
        "token_hash": approval.token_hash,
        "nonce": nonce,
        "expires_at": expires_at,
        "signature": sign_approval_proof(str(app.id), approval.token_hash, nonce, expires_utc),
    }
    return app, proof


async def submit_application(
    db: AsyncSession,
    user: User,
    app: Application,
    proof: dict,
    *,
    client: BrowserClient | None = None,
    request: Request | None = None,
) -> dict:
    if app.status != "APPROVED":
        raise HTTPException(
            status_code=409,
            detail=f"Submission requires an approved application (current: {app.status}).",
        )
    approval = (
        await db.execute(select(Approval).where(Approval.application_id == app.id))
    ).scalar_one_or_none()
    if approval is None or approval.used_at is not None:
        raise HTTPException(status_code=409, detail="No unused approval for this application.")
    if approval.approved_by != user.id:
        raise HTTPException(status_code=403, detail="This approval belongs to another user.")
    session = await _active_session(db, app)
    if session is None:
        raise HTTPException(status_code=409, detail="Browser session expired. Re-analyze and re-approve.")
    client = client or (browser_client if type(browser_client) is not BrowserClient else BrowserClient(base_url=session.worker_id or settings.BROWSER_WORKER_URL))

    app.submission_attempts += 1
    await _event(db, app, "submission_attempt", actor="browser", payload={"attempt": app.submission_attempts})
    try:
        result = await client.submit(session.session_ref, str(app.id), proof)
    except BrowserWorkerError as exc:
        # A timeout or connection drop after the click is genuinely unknown.
        unknown = exc.status_code in {504} or "unknown" in str(exc).lower()
        if unknown:
            app.failure_reason = str(exc)
            session.status = "UNKNOWN"
            await transition(
                db, app, "UNKNOWN_SUBMISSION_STATUS", actor="browser", payload={"error": str(exc)}
            )
            approval.used_at = datetime.now(timezone.utc)
            await audit.record(
                db,
                user_id=user.id,
                action="application.submission_unknown",
                resource_type="application",
                resource_id=app.id,
                details={"error": str(exc)},
                request=request,
            )
            await db.commit()
            await db.refresh(app)
            return {"application": app, "outcome": "UNKNOWN_SUBMISSION_STATUS", "evidence": {"reason": str(exc)}}
        await _event(db, app, "submission_rejected", actor="browser", payload={"error": str(exc)})
        await db.commit()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    screenshot = decode_screenshot(result.get("screenshot"))
    if screenshot:
        key = screenshot_key(str(user.id), str(app.id), "submitted")
        await storage.put(key, screenshot, "image/png")
        app.screenshot_s3_key = key
        session.screenshot_s3_key = key

    outcome = result.get("outcome")
    evidence = result.get("evidence")
    app.confirmation_evidence = {
        "outcome": outcome,
        "evidence": evidence,
        "final_url": result.get("final_url"),
        "validation_errors": result.get("validation_errors") or [],
        "missing_required": result.get("missing_required") or [],
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }
    session.status = outcome or "UNKNOWN"
    session.last_url = result.get("final_url") or session.last_url

    if outcome == "CONFIRMED":
        await transition(db, app, "SUBMITTED", actor="browser")
        await transition(db, app, "CONFIRMED", actor="browser", payload={"evidence": evidence})
        approval.used_at = datetime.now(timezone.utc)
        app.outcome = "submitted"
    elif outcome == "UNKNOWN_SUBMISSION_STATUS":
        await transition(
            db, app, "UNKNOWN_SUBMISSION_STATUS", actor="browser", payload={"evidence": evidence}
        )
        approval.used_at = datetime.now(timezone.utc)
        app.failure_reason = "Click performed but no confirmation was observed."
    elif outcome == "VALIDATION_FAILED":
        app.failure_reason = "The site rejected the form; nothing was submitted."
        approval.revoked_at = datetime.now(timezone.utc)
        await transition(
            db,
            app,
            "NEEDS_USER_INPUT",
            actor="browser",
            payload={
                "validation_errors": result.get("validation_errors"),
                "missing_required": result.get("missing_required"),
            },
        )
    else:
        app.failure_reason = (evidence or {}).get("reason") or "Submission could not be completed."
        approval.used_at = datetime.now(timezone.utc)
        await transition(db, app, "FAILED", actor="browser", payload={"evidence": evidence})

    await client.close(session.session_ref)
    session.status = "CLOSED"

    await audit.record(
        db,
        user_id=user.id,
        action=f"application.submit_{outcome.lower()}" if outcome else "application.submit_unknown",
        resource_type="application",
        resource_id=app.id,
        details={"outcome": outcome, "final_url": result.get("final_url")},
        request=request,
    )
    await db.commit()
    await db.refresh(app)
    return {
        "application": app,
        "outcome": outcome,
        "evidence": evidence,
        "validation_errors": result.get("validation_errors") or [],
    }


async def reject_application(
    db: AsyncSession, user: User, app: Application, reason: str | None, request: Request | None = None
) -> Application:
    if app.status not in {"USER_APPROVAL_PENDING", "APPROVED", "NEEDS_USER_INPUT", "FORM_ANALYZED"}:
        raise HTTPException(status_code=409, detail=f"Cannot reject an application in status {app.status}.")
    approval = (
        await db.execute(select(Approval).where(Approval.application_id == app.id))
    ).scalar_one_or_none()
    if approval:
        approval.revoked_at = datetime.now(timezone.utc)
    app.failure_reason = reason
    await transition(db, app, "CANCELLED", actor="user", payload={"reason": reason})
    session = await _active_session(db, app)
    if session and session.session_ref:
        await BrowserClient(base_url=session.worker_id or settings.BROWSER_WORKER_URL).close(session.session_ref)
        session.status = "CLOSED"
    await audit.record(
        db,
        user_id=user.id,
        action="application.rejected",
        resource_type="application",
        resource_id=app.id,
        details={"reason": reason},
        request=request,
    )
    await db.commit()
    await db.refresh(app)
    return app


async def mark_confirmed_manually(
    db: AsyncSession,
    user: User,
    app: Application,
    evidence_note: str,
    request: Request | None = None,
) -> Application:
    """A human can resolve an UNKNOWN status after checking the employer's site."""
    if app.status != "UNKNOWN_SUBMISSION_STATUS":
        raise HTTPException(status_code=409, detail="Only unknown submissions can be resolved manually.")
    if not evidence_note or len(evidence_note.strip()) < 5:
        raise HTTPException(status_code=422, detail="Describe what you saw on the employer's site.")
    app.confirmation_evidence = {
        **(app.confirmation_evidence or {}),
        "manual_confirmation": evidence_note.strip()[:2000],
        "confirmed_by_user_at": datetime.now(timezone.utc).isoformat(),
    }
    await transition(db, app, "CONFIRMED", actor="user", payload={"evidence": evidence_note[:200]})
    app.outcome = "submitted"
    await audit.record(
        db,
        user_id=user.id,
        action="application.manually_confirmed",
        resource_type="application",
        resource_id=app.id,
        details={"note": evidence_note[:200]},
        request=request,
    )
    await db.commit()
    await db.refresh(app)
    return app


async def record_outcome(
    db: AsyncSession,
    user: User,
    app: Application,
    outcome: str,
    note: str | None,
    request: Request | None = None,
) -> Application:
    allowed = {"interview", "offer", "rejected", "withdrawn", "no_response"}
    if outcome not in allowed:
        raise HTTPException(status_code=422, detail=f"Outcome must be one of {sorted(allowed)}.")
    app.outcome = outcome
    await _event(db, app, "outcome_recorded", actor="user", payload={"outcome": outcome, "note": note})
    await audit.record(
        db,
        user_id=user.id,
        action="application.outcome",
        resource_type="application",
        resource_id=app.id,
        details={"outcome": outcome},
        request=request,
    )
    await db.commit()
    await db.refresh(app)
    return app


async def _active_session(db: AsyncSession, app: Application) -> BrowserSession | None:
    session_id = (app.preview or {}).get("worker_session_id")
    if not session_id:
        return None
    return (
        await db.execute(
            select(BrowserSession)
            .where(
                BrowserSession.application_id == app.id,
                BrowserSession.session_ref == session_id,
                BrowserSession.status.in_(["ANALYZED", "FILLED"]),
            )
            .order_by(BrowserSession.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _answers(db: AsyncSession, app: Application) -> list[ApplicationAnswer]:
    return list(
        (
            await db.execute(
                select(ApplicationAnswer)
                .where(ApplicationAnswer.application_id == app.id)
                .order_by(ApplicationAnswer.created_at)
            )
        ).scalars()
    )


async def _replace_answers(
    db: AsyncSession, app: Application, answers: list[dict]
) -> None:
    existing = {answer.field_name: answer for answer in await _answers(db, app)}
    retained: set[str] = set()
    for payload in answers:
        field_name = payload["field_name"]
        retained.add(field_name)
        answer = existing.get(field_name)
        if answer is None:
            answer = ApplicationAnswer(application_id=app.id, field_name=field_name)
            db.add(answer)
        for key, value in payload.items():
            if key != "field_name" and hasattr(answer, key):
                setattr(answer, key, value)
    for field_name, answer in existing.items():
        if field_name not in retained:
            await db.delete(answer)
    await db.flush()


# --------------------------------------------------------------------------
# Answer preparation — deterministic and grounded in stored profile facts
# --------------------------------------------------------------------------

def prepare_answers(
    fields: list[dict],
    profile: CandidateProfile | None,
    resume_json: dict,
    job: Job,
    job_skills: list[str],
) -> tuple[list[dict], list[str], list[str]]:
    personal = (resume_json or {}).get("personal") or {}
    full_name = (profile.full_name if profile else None) or personal.get("full_name")
    email = (profile.email if profile else None) or personal.get("email")
    phone = (profile.phone if profile else None) or personal.get("phone")
    location = (profile.location if profile else None) or personal.get("location")
    links = {
        "linkedin": (profile.linkedin_url if profile else None) or personal.get("linkedin_url"),
        "github": (profile.github_url if profile else None) or personal.get("github_url"),
        "portfolio": (profile.portfolio_url if profile else None) or personal.get("portfolio_url"),
    }
    skills = list(profile.skills or resume_json.get("skills") or []) if profile else list(resume_json.get("skills") or [])
    education = (profile.education if profile else None) or resume_json.get("education") or []
    experience = (profile.experience if profile else None) or resume_json.get("experience") or []
    years = (profile.total_experience_years if profile else None) or resume_json.get("years_experience")
    first_name, last_name = _split_name(full_name)

    answers: list[dict] = []
    missing: list[str] = []
    warnings: list[str] = []

    for field in fields:
        label = (field.get("label") or field.get("placeholder") or field.get("name") or "").lower()
        name = (field.get("name") or "").lower()
        fingerprint = f"{label} {name}"
        field_type = field.get("type") or "text"
        value = None
        source = "profile"
        confidence = None

        if any(marker in fingerprint for marker in SENSITIVE_FIELD_MARKERS):
            warnings.append(
                f"'{field.get('label') or field.get('name')}' looks sensitive and was left blank for you to complete."
            )
            source = "needs_user"
        elif field_type == "file":
            value = "resume attached at fill time"
            source = "resume"
        elif _is_consent(fingerprint):
            source = "needs_user"
            warnings.append(
                f"Consent checkbox '{field.get('label') or field.get('name')}' was not auto-checked. "
                "Confirm it yourself before approving."
            )
        elif "cover" in fingerprint or any(marker in fingerprint for marker in COVER_LETTER_MARKERS):
            value = _cover_letter(full_name, job, skills, experience)
            source = "ai_template"
            confidence = 0.5 if value else None
            if value:
                warnings.append("A cover letter was drafted from your stored profile. Review and edit it.")
        elif "first" in fingerprint and "name" in fingerprint:
            value = first_name
        elif "last" in fingerprint and "name" in fingerprint:
            value = last_name
        elif "full name" in fingerprint or ("name" in fingerprint and "company" not in fingerprint and "user" not in fingerprint):
            value = full_name
        elif "email" in fingerprint:
            value = email
        elif "phone" in fingerprint or "mobile" in fingerprint or "contact number" in fingerprint:
            value = phone
        elif "linkedin" in fingerprint:
            value = links["linkedin"]
        elif "github" in fingerprint:
            value = links["github"]
        elif "portfolio" in fingerprint or "website" in fingerprint or "personal site" in fingerprint:
            value = links["portfolio"]
        elif "current company" in fingerprint or "present employer" in fingerprint:
            value = profile.current_company if profile else None
        elif "current title" in fingerprint or "job title" in fingerprint or "current role" in fingerprint:
            value = profile.current_title if profile else None
        elif ("year" in fingerprint and ("experience" in fingerprint or "exp" in fingerprint)):
            value = str(years) if years is not None else None
        elif "university" in fingerprint or "college" in fingerprint or "institution" in fingerprint or "school" in fingerprint:
            value = education[0].get("institution") if education else None
        elif "degree" in fingerprint or "qualification" in fingerprint:
            value = education[0].get("degree") if education else None
        elif "graduation" in fingerprint or ("year" in fingerprint and "pass" in fingerprint):
            value = str(education[0].get("graduation_year")) if education and education[0].get("graduation_year") else None
        elif "location" in fingerprint or "city" in fingerprint or "address" in fingerprint:
            value = location
        elif "country" in fingerprint:
            value = "India" if location and "india" in location.lower() else None
        elif "skill" in fingerprint:
            value = ", ".join(skills[:15]) if skills else None
        elif "salary" in fingerprint or "compensation" in fingerprint:
            value = str(int(profile.expected_salary)) if profile and profile.expected_salary else None

        if field.get("tag") == "select" and value:
            matched = _match_option(field.get("options") or [], value)
            if matched is None:
                warnings.append(
                    f"'{field.get('label')}' has no option matching '{value}'; please choose manually."
                )
                value = None
                source = "needs_user"

        if value is None and not field.get("required"):
            continue
        if value is None and field.get("required"):
            missing.append(field.get("label") or field.get("name") or field.get("ref"))
        answers.append(
            {
                "field_name": field["ref"],
                "field_label": field.get("label") or field.get("name") or field["ref"],
                "field_type": field_type,
                "field_value": value,
                "source": source,
                "confidence": confidence,
                "is_required": bool(field.get("required")),
                "is_user_edited": False,
            }
        )
    return answers, missing, warnings


def _split_name(full_name: str | None) -> tuple[str | None, str | None]:
    if not full_name or not full_name.strip():
        return None, None
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _cover_letter(full_name: str | None, job: Job, skills: list[str], experience: list[dict]) -> str | None:
    if not full_name or not skills:
        return None
    latest = experience[0] if experience else None
    background = ""
    if latest and isinstance(latest, dict) and latest.get("title"):
        background = f" In my most recent role as {latest['title']}"
        if latest.get("company"):
            background += f" at {latest['company']}"
        background += "."
    return (
        f"Dear {job.company} hiring team,\n\n"
        f"I am applying for the {job.title} role. My background includes "
        f"{', '.join(skills[:8])}.{background}\n\n"
        "I would welcome the chance to discuss how my experience can contribute to your team.\n\n"
        f"Best regards,\n{full_name}"
    )


def _is_consent(fingerprint: str) -> bool:
    return any(marker in fingerprint for marker in CONSENT_MARKERS)


def _match_option(options: list[dict], value: str) -> str | None:
    target = value.strip().lower()
    for option in options:
        if option.get("disabled"):
            continue
        if str(option.get("value", "")).strip().lower() == target:
            return str(option["value"])
        if str(option.get("label", "")).strip().lower() == target:
            return str(option["value"])
    for option in options:
        if not option.get("disabled") and target in str(option.get("label", "")).lower():
            return str(option["value"])
    return None
