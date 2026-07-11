"""FastAPI application entrypoint for the GRIDIX control plane."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.config import get_settings
from app.errors import install_error_handlers
from app.logging import configure_logging
from app.ratelimit import RateLimitMiddleware, RequestSizeLimitMiddleware
from app.redis_client import close_redis
from app.routes import (
    agent,
    blobs,
    endpoints,
    health,
    jobs,
    metrics,
    providers,
    registration,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Configure logging on startup; release Redis on shutdown."""
    configure_logging()
    settings = get_settings()
    logger.info("GRIDIX API starting (env={})", settings.env)
    yield
    await close_redis()
    logger.info("GRIDIX API stopped")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(title="GRIDIX Control Plane", version="0.1.0", lifespan=lifespan)
    # Outer-most first: reject oversized bodies before counting them against rate limits.
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware)
    install_error_handlers(app)

    app.include_router(health.router)
    app.include_router(registration.router)
    app.include_router(blobs.router)
    app.include_router(jobs.router)
    app.include_router(providers.router)
    app.include_router(agent.router)
    app.include_router(endpoints.router)
    app.include_router(metrics.router)
    return app


app = create_app()
