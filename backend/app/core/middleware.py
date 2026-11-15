"""
HTTP middleware: request IDs, browser hardening headers, and a SameSite/Origin
check for cookie-authenticated state changes.

Bearer-token clients are unaffected. Cookie-authenticated unsafe requests must
carry an Origin (or Referer) that matches an allowed frontend origin, which is
what stops a third-party page from driving the API with a stolen cookie.
"""
from __future__ import annotations

import uuid
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path not in {"/docs", "/redoc", "/openapi.json"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            )
        if settings.ENVIRONMENT == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        return response


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if (
            request.method in UNSAFE_METHODS
            and settings.SESSION_COOKIE_NAME in request.cookies
            and "authorization" not in {k.lower() for k in request.headers.keys()}
        ):
            origin = request.headers.get("origin")
            if not origin:
                referer = request.headers.get("referer")
                if referer:
                    parsed = urlparse(referer)
                    origin = f"{parsed.scheme}://{parsed.netloc}"
            allowed = {o.rstrip("/") for o in settings.cors_origins}
            if not origin or origin.rstrip("/") not in allowed:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Cross-site request blocked. Sign in again and retry from the app."
                    },
                )
        return await call_next(request)
