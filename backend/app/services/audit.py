"""Append-only audit trail. Callers commit the transaction."""
from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import AuditLog


async def record(
    db: AsyncSession,
    *,
    user_id: Any = None,
    action: str,
    resource_type: str | None = None,
    resource_id: Any = None,
    details: dict | None = None,
    request: Request | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else None,
        details=details or {},
        ip_address=_client_ip(request) if request else None,
        user_agent=(request.headers.get("user-agent") or "")[:500] if request else None,
    )
    db.add(entry)
    return entry


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host[:64] if request.client else None
