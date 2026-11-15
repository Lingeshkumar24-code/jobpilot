"""
HTTP client for the isolated browser worker.

The backend never launches Chromium itself. It sends the approved form values
to the worker and receives a structured observation back. A worker timeout is
treated as UNKNOWN_SUBMISSION_STATUS by the caller — not as failure, because a
click may already have happened.
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone

import httpx

from app.core.config import settings


class BrowserWorkerError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class BrowserClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.BROWSER_WORKER_URL).rstrip("/")
        self.secret = settings.BROWSER_WORKER_SECRET
        self.timeout = httpx.Timeout(120.0, connect=10.0)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.secret)

    async def health(self) -> dict:
        """Short, non-blocking reachability probe used by the status page."""
        if not self.configured:
            return {"configured": False, "reachable": None, "detail": "Not configured"}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
                response = await client.get(
                    f"{self.base_url}/health", headers={"X-Worker-Secret": self.secret}
                )
            if response.status_code >= 400:
                return {
                    "configured": True,
                    "reachable": False,
                    "detail": f"HTTP {response.status_code}",
                }
            data = response.json()
            return {
                "configured": True,
                "reachable": True,
                "detail": str(data.get("status", "ok")),
            }
        except (httpx.HTTPError, ValueError):
            return {"configured": True, "reachable": False, "detail": "Unreachable"}

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        if not self.configured:
            raise BrowserWorkerError(
                "Browser worker is not configured (BROWSER_WORKER_URL / BROWSER_WORKER_SECRET).",
                status_code=503,
            )
        headers = {"X-Worker-Secret": self.secret}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method, f"{self.base_url}{path}", json=json, headers=headers
                )
        except httpx.TimeoutException as exc:
            raise BrowserWorkerError(
                "Browser worker did not respond in time. Submission status is unknown.",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise BrowserWorkerError(
                "Browser worker is unreachable.", status_code=503
            ) from exc

        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", "Browser worker rejected the request.")
            except ValueError:
                detail = "Browser worker rejected the request."
            raise BrowserWorkerError(str(detail), status_code=response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            raise BrowserWorkerError("Browser worker returned invalid JSON.") from exc

    async def analyze(
        self,
        url: str,
        application_id: str,
        resume_bytes: bytes | None,
        resume_filename: str | None,
    ) -> dict:
        payload: dict = {"url": url, "application_id": application_id}
        if resume_bytes:
            payload["resume"] = {
                "filename": resume_filename or "resume.pdf",
                "content_base64": base64.b64encode(resume_bytes).decode(),
            }
        return await self._request("POST", "/v1/sessions/analyze", payload)

    async def fill(self, session_id: str, values: dict[str, str], upload_resume: bool = True) -> dict:
        return await self._request(
            "POST",
            f"/v1/sessions/{session_id}/fill",
            {"values": values, "upload_resume": upload_resume},
        )

    async def submit(self, session_id: str, application_id: str, proof: dict) -> dict:
        return await self._request(
            "POST",
            f"/v1/sessions/{session_id}/submit",
            {"application_id": application_id, "approval": proof},
        )

    async def close(self, session_id: str) -> None:
        try:
            await self._request("DELETE", f"/v1/sessions/{session_id}")
        except BrowserWorkerError:
            pass


browser_client = BrowserClient()


def decode_screenshot(payload: dict | None) -> bytes | None:
    if not payload or not payload.get("base64"):
        return None
    try:
        return base64.b64decode(payload["base64"])
    except (ValueError, TypeError):
        return None


def screenshot_key(user_id: str, application_id: str, suffix: str) -> str:
    digest = hashlib.sha256(f"{application_id}:{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()[:16]
    return f"screenshots/{user_id}/{application_id}/{digest}-{suffix}.png"
