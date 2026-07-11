"""Liveness/readiness probe — verifies DB and Redis connectivity."""

from fastapi import APIRouter, Response, status
from loguru import logger
from sqlalchemy import text

from app.db import get_sessionmaker
from app.redis_client import get_redis
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


async def _check_db() -> bool:
    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 — probe reports any failure as down
        logger.warning("health: database check failed: {}", exc)
        return False


async def _check_redis() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception as exc:  # noqa: BLE001 — probe reports any failure as down
        logger.warning("health: redis check failed: {}", exc)
        return False


@router.get("/health", response_model=HealthResponse)
async def health(response: Response) -> HealthResponse:
    """Return 200 only when both Postgres and Redis are reachable, else 503."""
    db_ok = await _check_db()
    redis_ok = await _check_redis()
    healthy = db_ok and redis_ok
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="ok" if healthy else "degraded", database=db_ok, redis=redis_ok)
