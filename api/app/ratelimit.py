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


def _bump_local(identity: str, window: int) -> int:
    """Increment and return the per-process counter for ``(identity, window)``."""
    for k in [k for k in _local_windows if k[1] < window - 1]:
        del _local_windows[k]
    count = _local_windows.get((identity, window), 0) + 1
    _local_windows[(identity, window)] = count
    return count


def _check_local(identity: str, window: int, limit: int) -> bool:
    """Fail-closed fallback: a per-process fixed-window counter.

    Bounded by ``limit`` per process per window (at most limit×replicas overall) — never
    unlimited, so a Redis outage degrades to a stricter local cap, not an open door.
    """
    return _bump_local(identity, window) <= limit


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


# ── failed-authentication budget (pentest H8) ──────────────────────────────────────────
# Same fixed-window, fail-closed shape as check_rate_limit, but split into a read-only
# "exceeded?" and a "record" half so that only FAILURES spend the budget. Counting every
# attempt instead would throttle a legitimate provider that reconnects often (many agents
# behind one NAT egress IP), while counting failures only touches an attacker: a provider
# holding a valid key never fails.


def _fail_key(identity: str, window: int) -> str:
    return f"gridix:authfail:{identity}:{window}"


async def record_auth_failure(identity: str, window_seconds: int = 60) -> None:
    """Charge one failed authentication to ``identity``'s budget for this window."""
    window = int(time.time()) // window_seconds
    key = _fail_key(identity, window)
    try:
        redis = get_redis()
        if await redis.incr(key) == 1:
            await redis.expire(key, window_seconds)
    except Exception as exc:  # noqa: BLE001 - fail CLOSED: still count it, per-process
        logger.warning("auth-failure counter: Redis unavailable, using local fallback: {}", exc)
        _bump_local(_fail_key(identity, 0), window)


async def auth_failures_exceeded(identity: str, limit: int, window_seconds: int = 60) -> bool:
    """True once ``identity`` has burned its failed-auth budget. Never increments."""
    window = int(time.time()) // window_seconds
    try:
        redis = get_redis()
        count = int(await redis.get(_fail_key(identity, window)) or 0)
    except Exception as exc:  # noqa: BLE001 - fail CLOSED: trust the per-process count
        logger.warning("auth-failure counter: Redis unavailable, using local fallback: {}", exc)
        count = _local_windows.get((_fail_key(identity, 0), window), 0)
    return count >= limit


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
