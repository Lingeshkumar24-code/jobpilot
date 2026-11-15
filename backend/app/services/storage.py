"""
Private resume storage.

Two backends:
  * S3 (production) — private bucket, server-side encryption, short-lived
    presigned GET URLs.
  * Local filesystem (development/tests) — files live outside the repo and
    are served through an authenticated endpoint with a signed, expiring
    token. The local backend exists so development never needs cloud creds;
    it is not a production fallback.

Keys are always generated server-side from the authenticated user id. A
client-supplied filename is never used as a path.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from jose import JWTError, jwt

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    pass


class StorageService:
    def __init__(self) -> None:
        self.backend = self._resolve_backend()
        self.local_root = Path(settings.LOCAL_STORAGE_DIR)
        self._s3 = None
        if self.backend == "s3":
            self.local_root.mkdir(parents=True, exist_ok=True)
            try:
                self._s3 = boto3.client(
                    "s3",
                    region_name=settings.AWS_REGION,
                    endpoint_url=settings.S3_ENDPOINT_URL,
                )
            except Exception as exc:  # pragma: no cover - env dependent
                raise StorageError(f"Could not create S3 client: {exc}") from exc
        else:
            self.local_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _resolve_backend() -> str:
        configured = settings.STORAGE_BACKEND.lower()
        if configured in {"s3", "local"}:
            return configured
        # "auto": use S3 only when explicitly enabled; otherwise local.
        return "local"

    def build_key(self, user_id: str, filename: str) -> str:
        suffix = Path(filename).suffix.lower().lstrip(".") or "bin"
        return f"resumes/{user_id}/{uuid.uuid4().hex}.{suffix}"

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        if self.backend == "s3":
            await self._s3_put(key, data, content_type)
        else:
            path = self._local_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_bytes, data)

    async def get(self, key: str) -> bytes:
        if self.backend == "s3":
            return await self._s3_get(key)
        path = self._local_path(key)
        if not path.exists():
            raise StorageError("Stored file not found")
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, key: str) -> None:
        if self.backend == "s3":
            try:
                await asyncio.to_thread(
                    self._s3.delete_object, Bucket=settings.S3_BUCKET_RESUMES, Key=key
                )
            except (BotoCoreError, ClientError) as exc:
                logger.warning("S3 delete failed for %s: %s", key, type(exc).__name__)
        else:
            path = self._local_path(key)
            if path.exists():
                await asyncio.to_thread(path.unlink)

    async def presigned_url(self, key: str, resume_id: str) -> tuple[str, int]:
        """Return (url, expires_in_seconds)."""
        expires = settings.S3_PRESIGN_EXPIRE_SECONDS
        if self.backend == "s3":
            url = await asyncio.to_thread(
                self._s3.generate_presigned_url,
                "get_object",
                Params={"Bucket": settings.S3_BUCKET_RESUMES, "Key": key},
                ExpiresIn=expires,
            )
            return url, expires
        token = jwt.encode(
            {
                "sub": resume_id,
                "typ": "download",
                "exp": datetime.now(timezone.utc) + timedelta(seconds=expires),
            },
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        return f"{settings.APP_BASE_URL}/api/v1/resumes/{resume_id}/download?token={token}", expires

    def verify_download_token(self, token: str, resume_id: str) -> bool:
        try:
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        except JWTError:
            return False
        return payload.get("typ") == "download" and payload.get("sub") == resume_id

    # -- helpers -----------------------------------------------------------

    def _local_path(self, key: str) -> Path:
        root = self.local_root.resolve()
        path = (root / key).resolve()
        if root not in path.parents and path != root:
            raise StorageError("Invalid storage key")
        return path

    async def _s3_put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            await asyncio.to_thread(
                self._s3.put_object,
                Bucket=settings.S3_BUCKET_RESUMES,
                Key=key,
                Body=data,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError("Could not upload the file to private storage") from exc

    async def _s3_get(self, key: str) -> bytes:
        try:
            response = await asyncio.to_thread(
                self._s3.get_object, Bucket=settings.S3_BUCKET_RESUMES, Key=key
            )
            return await asyncio.to_thread(response["Body"].read)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError("Could not read the file from private storage") from exc


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


storage = StorageService()
