"""FastAPI application entrypoint for the GRIDIX control plane."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.chain.bootstrap import install_chain
from app.config import get_settings
from app.errors import install_error_handlers
from app.logging import configure_logging
from app.ratelimit import RateLimitMiddleware, RequestSizeLimitMiddleware
from app.redis_client import close_redis
from app.routes import (
    agent,
    api_keys,
    auth,
    billing,
    blobs,
    disputes,
    endpoints,
    events,
    health,
    inference,
    jobs,
    metrics,
    providers,
    public,
    registration,
    uploads,
)
from app.secret_manager import init_secrets


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Configure logging on startup; release Redis on shutdown."""
    configure_logging()
    settings = get_settings()
    # Fail fast if secrets are misconfigured — before serving a single request.
    init_secrets(settings)
    # Install the on-chain payment provider so the submit gate reads on-chain balances
    # (no-op when chain_enabled is false — the process stays fiat-only).
    await install_chain(settings)
    logger.info("GRIDIX API starting (env={})", settings.env)
    yield
    await close_redis()
    logger.info("GRIDIX API stopped")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(title="GRIDIX Control Plane", version="0.1.0", lifespan=lifespan)
    # Outer-most first: reject oversized bodies before counting them against rate limits.
    # CORS (security wave 3): only explicitly allowlisted origins, never "*". Empty by
    # default — the frontend calls the API through a same-origin proxy, so it needs none.
    origins = get_settings().cors_origins_list
    if origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware)
    install_error_handlers(app)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(api_keys.router)
    app.include_router(inference.router)
    app.include_router(public.router)
    app.include_router(registration.router)
    app.include_router(billing.router)
    app.include_router(blobs.router)
    app.include_router(uploads.router)
    app.include_router(jobs.router)
    app.include_router(events.router)
    app.include_router(providers.router)
    app.include_router(agent.router)
    app.include_router(disputes.router)
    app.include_router(endpoints.router)
    app.include_router(metrics.router)
    return app


app = create_app()
