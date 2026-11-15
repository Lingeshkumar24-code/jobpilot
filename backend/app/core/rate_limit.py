"""
Small in-process rate limiter used to blunt credential stuffing and abusive
search calls. In production the API Gateway usage plan / WAF is the primary
control; this is the application-level safety net (and it is testable).
"""
import asyncio
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.core.config import settings


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        now = time.monotonic()
        async with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= now - self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = max(1, int(bucket[0] + self.window - now))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please wait and try again.",
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)

    def reset(self) -> None:
        self._hits.clear()


auth_limiter = RateLimiter(settings.RATE_LIMIT_AUTH_PER_MINUTE)
search_limiter = RateLimiter(settings.RATE_LIMIT_SEARCH_PER_MINUTE)
write_limiter = RateLimiter(settings.RATE_LIMIT_WRITE_PER_MINUTE)


def client_key(request: Request, scope: str) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    return f"{scope}:{ip}"


async def limit_auth(request: Request) -> None:
    await auth_limiter.check(client_key(request, "auth"))


async def limit_search(request: Request) -> None:
    await search_limiter.check(client_key(request, "search"))


async def limit_write(request: Request) -> None:
    await write_limiter.check(client_key(request, "write"))
