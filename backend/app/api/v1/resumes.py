"""
Resume upload, parsing and download.

Uploads are validated by magic bytes (not by the extension), size-capped, and
stored under a server-generated key. Parsing is deterministic first; the
optional LLM pass is validated against the extracted text and can never add a
value that is not present in the document.
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import limit_write
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.core import CandidateProfile, ResumeFile, ResumeVersion, User
from app.schemas.resume import (
    DownloadUrlOut,
    ReparseRequest,
    ResumeDetail,
    ResumeFileOut,
    ResumeUploadResponse,
    ResumeVersionOut,
)
from app.services import audit
from app.services.resume_extractor import (
    _extract_with_llm_async,
    completeness,
    extract_profile,
)
from app.services.resume_parser import ResumeParseError, extract_text
from app.services.storage import StorageError, checksum, storage

router = APIRouter()

ALLOWED_TYPES = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def _validate_upload(data: bytes, filename: str) -> str:
    if len(data) > settings.MAX_RESUME_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Resume exceeds the {settings.MAX_RESUME_BYTES // (1024 * 1024)} MB limit.",
        )
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    if suffix == "pdf":
        if not data.startswith(b"%PDF-"):
            raise HTTPException(status_code=415, detail="This file is not a valid PDF.")
        return "pdf"
    if suffix == "docx":
        if not data.startswith(b"PK\x03\x04"):
            raise HTTPException(status_code=415, detail="This file is not a valid DOCX.")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if "word/document.xml" not in archive.namelist():
                    raise HTTPException(status_code=415, detail="This DOCX has no document body.")
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=415, detail="This DOCX is corrupted.") from exc
        return "docx"
    raise HTTPException(status_code=415, detail="Only PDF and DOCX resumes are accepted.")


def _safe_filename(filename: str) -> str:
    name = Path(filename or "resume").name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = re.sub(r"[^\w.\- ]", "_", name)
    return name[:200] or "resume"


def _apply_to_profile(profile: CandidateProfile, extracted: dict, user: User) -> None:
    personal = extracted.get("personal") or {}
    scalar_map = {
        "full_name": personal.get("full_name"),
        "phone": personal.get("phone"),
        "location": personal.get("location"),
        "headline": extracted.get("headline"),
        "summary": extracted.get("summary"),
        "linkedin_url": personal.get("linkedin_url"),
        "github_url": personal.get("github_url"),
        "portfolio_url": personal.get("portfolio_url"),
    }
    for field, value in scalar_map.items():
        if value and not getattr(profile, field, None):
            setattr(profile, field, value)

    # The contact email on the resume is what employers should reply to. The
    # login email is only a placeholder until the resume supplies one.
    resume_email = personal.get("email")
    if resume_email and (not profile.email or profile.email == user.email):
        profile.email = resume_email

    skills = list(profile.skills or [])
    for skill in extracted.get("skills") or []:
        if skill not in skills:
            skills.append(skill)
    profile.skills = skills

    for field in ("education", "experience", "projects", "certifications", "achievements", "languages"):
        if not getattr(profile, field, None) and extracted.get(field):
            setattr(profile, field, extracted[field])

    if profile.total_experience_years is None and extracted.get("years_experience") is not None:
        profile.total_experience_years = extracted["years_experience"]
    if not profile.current_title and extracted.get("experience"):
        latest = extracted["experience"][0]
        if isinstance(latest, dict):
            profile.current_title = latest.get("title")
            profile.current_company = latest.get("company")
    profile.extracted_data = extracted
    profile.completeness = completeness(extracted)


async def _parse_resume(data: bytes, file_type: str, use_llm: bool) -> dict:
    text = extract_text(data, file_type, settings.MAX_RESUME_PAGES)
    profile = extract_profile(text)
    if use_llm:
        try:
            profile = await _extract_with_llm_async(text, profile)
        except Exception:
            # AI is an enhancement; deterministic extraction already succeeded.
            pass
    return profile


def _file_out(resume: ResumeFile) -> ResumeFileOut:
    return ResumeFileOut.model_validate(resume)


def _version_out(version: ResumeVersion) -> ResumeVersionOut:
    return ResumeVersionOut.model_validate(version)


@router.post(
    "/upload",
    response_model=ResumeUploadResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_write)],
)
async def upload_resume(
    request: Request,
    file: Annotated[UploadFile, File(description="PDF or DOCX resume")],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    use_llm: bool = True,
):
    data = await file.read(settings.MAX_RESUME_BYTES + 1)
    filename = _safe_filename(file.filename or "resume")
    file_type = _validate_upload(data, filename)

    try:
        extracted = await _parse_resume(data, file_type, use_llm)
    except ResumeParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    key = storage.build_key(str(current_user.id), filename)
    try:
        await storage.put(key, data, ALLOWED_TYPES[file_type])
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    existing_count = (
        await db.execute(
            select(func.count(ResumeFile.id)).where(
                ResumeFile.user_id == current_user.id, ResumeFile.deleted_at.is_(None)
            )
        )
    ).scalar_one()

    resume = ResumeFile(
        user_id=current_user.id,
        s3_key=key,
        storage_backend=storage.backend,
        original_filename=filename,
        file_type=file_type,
        content_type=ALLOWED_TYPES[file_type],
        size_bytes=len(data),
        checksum_sha256=checksum(data),
        status="parsed",
        parsed_at=datetime.now(timezone.utc),
        is_primary=existing_count == 0,
    )
    db.add(resume)
    await db.flush()

    version = ResumeVersion(
        resume_file_id=resume.id,
        user_id=current_user.id,
        version_number=1,
        parsed_json=extracted,
        extraction_method=extracted.get("extraction_method", "heuristic"),
        is_active=True,
    )
    db.add(version)

    profile = (
        await db.execute(select(CandidateProfile).where(CandidateProfile.user_id == current_user.id))
    ).scalar_one_or_none()
    if profile is None:
        profile = CandidateProfile(user_id=current_user.id, email=current_user.email)
        db.add(profile)
        await db.flush()
    _apply_to_profile(profile, extracted, current_user)

    await audit.record(
        db,
        user_id=current_user.id,
        action="resume.uploaded",
        resource_type="resume",
        resource_id=resume.id,
        details={
            "filename": filename,
            "size_bytes": len(data),
            "file_type": file_type,
            "extraction_method": version.extraction_method,
            "completeness": profile.completeness,
        },
        request=request,
    )
    await db.commit()
    await db.refresh(resume)
    await db.refresh(version)

    warnings = []
    if extracted.get("rejected_llm_fields"):
        warnings.append(
            f"{len(extracted['rejected_llm_fields'])} AI-suggested values were discarded because "
            "they were not present in the resume text."
        )
    if extracted.get("missing_fields"):
        warnings.append(
            "Some details were not found in the resume: " + ", ".join(extracted["missing_fields"])
        )
    return ResumeUploadResponse(
        file=_file_out(resume),
        version=_version_out(version),
        completeness=profile.completeness,
        missing_fields=extracted.get("missing_fields") or [],
        warnings=warnings,
    )


@router.get("", response_model=list[ResumeFileOut])
async def list_resumes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(ResumeFile)
            .where(ResumeFile.user_id == current_user.id, ResumeFile.deleted_at.is_(None))
            .order_by(ResumeFile.created_at.desc())
        )
    ).scalars().all()
    return [_file_out(row) for row in rows]


@router.get("/{resume_id}", response_model=ResumeDetail)
async def get_resume(
    resume_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    resume = await _owned_resume(db, current_user, resume_id)
    versions = (
        await db.execute(
            select(ResumeVersion)
            .where(ResumeVersion.resume_file_id == resume.id)
            .order_by(ResumeVersion.version_number.desc())
        )
    ).scalars().all()
    active = next((v for v in versions if v.is_active), versions[0] if versions else None)
    profile = (
        await db.execute(select(CandidateProfile).where(CandidateProfile.user_id == current_user.id))
    ).scalar_one_or_none()
    return ResumeDetail(
        file=_file_out(resume),
        versions=[_version_out(v) for v in versions],
        active_version=_version_out(active) if active else None,
        completeness=profile.completeness if profile else 0,
    )


@router.get("/{resume_id}/versions", response_model=list[ResumeVersionOut])
async def list_versions(
    resume_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    resume = await _owned_resume(db, current_user, resume_id)
    versions = (
        await db.execute(
            select(ResumeVersion)
            .where(ResumeVersion.resume_file_id == resume.id)
            .order_by(ResumeVersion.version_number.desc())
        )
    ).scalars().all()
    return [_version_out(v) for v in versions]


@router.post("/{resume_id}/reparse", response_model=ResumeUploadResponse)
async def reparse_resume(
    resume_id: UUID,
    payload: ReparseRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    resume = await _owned_resume(db, current_user, resume_id)
    try:
        data = await storage.get(resume.s3_key)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        extracted = await _parse_resume(data, resume.file_type, payload.use_llm)
    except ResumeParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    latest = (
        await db.execute(
            select(ResumeVersion)
            .where(ResumeVersion.resume_file_id == resume.id)
            .order_by(ResumeVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    for version in (
        await db.execute(select(ResumeVersion).where(ResumeVersion.resume_file_id == resume.id))
    ).scalars():
        version.is_active = False
    version = ResumeVersion(
        resume_file_id=resume.id,
        user_id=current_user.id,
        version_number=(latest.version_number + 1) if latest else 1,
        parsed_json=extracted,
        extraction_method=extracted.get("extraction_method", "heuristic"),
        is_active=True,
    )
    db.add(version)
    resume.status = "parsed"
    resume.parsed_at = datetime.now(timezone.utc)

    profile = (
        await db.execute(select(CandidateProfile).where(CandidateProfile.user_id == current_user.id))
    ).scalar_one_or_none()
    if profile:
        _apply_to_profile(profile, extracted, current_user)
    await audit.record(
        db,
        user_id=current_user.id,
        action="resume.reparsed",
        resource_type="resume",
        resource_id=resume.id,
        details={"use_llm": payload.use_llm, "method": version.extraction_method},
        request=request,
    )
    await db.commit()
    await db.refresh(resume)
    await db.refresh(version)
    return ResumeUploadResponse(
        file=_file_out(resume),
        version=_version_out(version),
        completeness=profile.completeness if profile else 0,
        missing_fields=extracted.get("missing_fields") or [],
        warnings=[],
    )


@router.post("/{resume_id}/primary", response_model=ResumeFileOut)
async def set_primary(
    resume_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    resume = await _owned_resume(db, current_user, resume_id)
    for other in (
        await db.execute(select(ResumeFile).where(ResumeFile.user_id == current_user.id))
    ).scalars():
        other.is_primary = other.id == resume.id
    await db.commit()
    await db.refresh(resume)
    return _file_out(resume)


@router.get("/{resume_id}/url", response_model=DownloadUrlOut)
async def download_url(
    resume_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    resume = await _owned_resume(db, current_user, resume_id)
    try:
        url, expires = await storage.presigned_url(resume.s3_key, str(resume.id))
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return DownloadUrlOut(url=url, expires_in=expires)


@router.get("/{resume_id}/download")
async def download_resume(
    resume_id: UUID,
    request: Request,
    token: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    resume = (
        await db.execute(
            select(ResumeFile).where(
                ResumeFile.id == resume_id, ResumeFile.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")

    authorized = bool(token and storage.verify_download_token(token, str(resume.id)))
    if not authorized:
        auth_header = request.headers.get("authorization", "")
        bearer = auth_header[7:] if auth_header.lower().startswith("bearer ") else None
        raw_token = bearer or request.cookies.get(settings.SESSION_COOKIE_NAME)
        user_id = decode_access_token(raw_token) if raw_token else None
        if not user_id or str(resume.user_id) != user_id:
            raise HTTPException(status_code=401, detail="Not authorized to download this file")

    try:
        data = await storage.get(resume.s3_key)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    filename = _safe_filename(resume.original_filename)
    return StreamingResponse(
        io.BytesIO(data),
        media_type=resume.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    resume = await _owned_resume(db, current_user, resume_id)
    resume.deleted_at = datetime.now(timezone.utc)
    resume.is_primary = False
    for version in (
        await db.execute(select(ResumeVersion).where(ResumeVersion.resume_file_id == resume.id))
    ).scalars():
        version.is_active = False
        version.deleted_at = datetime.now(timezone.utc)
    await storage.delete(resume.s3_key)
    replacement = (
        await db.execute(
            select(ResumeFile)
            .where(ResumeFile.user_id == current_user.id, ResumeFile.id != resume.id, ResumeFile.deleted_at.is_(None))
            .order_by(ResumeFile.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if replacement:
        replacement.is_primary = True
    await audit.record(
        db,
        user_id=current_user.id,
        action="resume.deleted",
        resource_type="resume",
        resource_id=resume.id,
        request=request,
    )
    await db.commit()
    return None


async def _owned_resume(db: AsyncSession, user: User, resume_id: UUID) -> ResumeFile:
    try:
        resume_uuid = UUID(str(resume_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Resume not found") from exc
    resume = (
        await db.execute(
            select(ResumeFile).where(
                ResumeFile.id == resume_uuid,
                ResumeFile.user_id == user.id,
                ResumeFile.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume

