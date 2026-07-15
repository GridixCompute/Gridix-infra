"""Rate limiting and request-size limiting middleware.

Rate limiting is a per-identity fixed-window counter in Redis (shared across API
replicas). It fails *closed* (security wave 2): if Redis is unreachable it falls back to a
per-process in-memory counter that STILL enforces the limit, so an attacker cannot remove
the limit by flooding until Redis tips over. The size limiter rejects oversized bodies up
front via ``Content-Length``.
"""

import time

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings
from app.redis_client import get_redis

# Per-process fallback counters used ONLY when Redis is unreachable. Keyed by
# (identity, window); pruned to the current + previous window so it can't grow.
_local_windows: dict[tuple[str, int], int] = {}


def _check_local(identity: str, window: int, limit: int) -> bool:
    """Fail-closed fallback: a per-process fixed-window counter.

    Bounded by ``limit`` per process per window (at most limit×replicas overall) — never
    unlimited, so a Redis outage degrades to a stricter local cap, not an open door.
    """
    for k in [k for k in _local_windows if k[1] < window - 1]:
        del _local_windows[k]
    count = _local_windows.get((identity, window), 0) + 1
    _local_windows[(identity, window)] = count
    return count <= limit


def _identity(request: Request) -> str:
    """Rate-limit key: the API key if present, else the client IP."""
    auth = request.headers.get("authorization")
    if auth:
        return f"key:{hash(auth)}"
    client = request.client
    return f"ip:{client.host if client else 'unknown'}"


async def check_rate_limit(identity: str, limit: int, window_seconds: int = 60) -> bool:
    """Return True if the request is within the limit for the current window.

    Fixed-window counter keyed by identity and window. Fails CLOSED via a local
    fallback counter when Redis is unreachable.
    """
    window = int(time.time()) // window_seconds
    key = f"gridix:ratelimit:{identity}:{window}"
    try:
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds)
        return count <= limit
    except Exception as exc:  # noqa: BLE001 - fail CLOSED: fall back to the local counter
        logger.warning("rate limit: Redis unavailable, using local fallback: {}", exc)
        return _check_local(identity, window, limit)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests once an identity exceeds ``rate_limit_per_minute``."""

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        allowed = await check_rate_limit(_identity(request), settings.rate_limit_per_minute)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"error": {"type": "rate_limited", "message": "Too many requests."}},
            )
        return await call_next(request)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose declared body exceeds ``max_request_bytes``."""

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        content_length = request.headers.get("content-length")
        if (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > settings.max_request_bytes
        ):
            return JSONResponse(
                status_code=413,
                content={
                    "error": {"type": "payload_too_large", "message": "Request body too large."}
                },
            )
        return await call_next(request)
