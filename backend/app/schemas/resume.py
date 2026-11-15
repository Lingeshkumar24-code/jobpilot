from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ResumeFileOut(BaseModel):
    id: UUID
    original_filename: str
    file_type: str
    size_bytes: int
    status: str
    is_primary: bool
    checksum_sha256: str | None = None
    error: str | None = None
    parsed_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ResumeVersionOut(BaseModel):
    id: UUID
    resume_file_id: UUID
    version_number: int
    extraction_method: str
    is_active: bool
    parsed_json: dict[str, Any] | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ResumeUploadResponse(BaseModel):
    file: ResumeFileOut
    version: ResumeVersionOut
    completeness: int = 0
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ResumeDetail(BaseModel):
    file: ResumeFileOut
    versions: list[ResumeVersionOut]
    active_version: ResumeVersionOut | None = None
    completeness: int = 0


class ReparseRequest(BaseModel):
    use_llm: bool = True


class DownloadUrlOut(BaseModel):
    url: str
    expires_in: int


