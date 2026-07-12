"""Scheduler worker — a separate process (``python -m app.scheduler``).

Runs two cooperating loops:

* **assignment loop** — blocks on the Redis queue, assigns each dequeued job to a
  capable provider (requeuing after a short delay if none fits).
* **reaper loop** — periodically reclaims jobs whose lease lapsed, requeuing them or
  failing them once the attempt budget is spent.

Both are concurrency-safe, so running several scheduler replicas is fine.
"""

import asyncio
import random
import signal

from loguru import logger

from app.assignment import (
    assign_job,
    drain_unreachable_providers,
    reap_expired_attempts,
    reap_expired_leases,
    recover_queued_jobs,
)
from app.canary import create_canary_job
from app.config import get_settings
from app.db import get_sessionmaker
from app.logging import configure_logging
from app.matcher import ReputationMatcher, set_matcher
from app.redis_client import close_redis, dequeue_job, enqueue_job
from app.secret_manager import init_secrets

# How long to wait before retrying a job that currently has no eligible provider.
_REQUEUE_DELAY_SECONDS = 2.0


async def _assignment_loop(stop: asyncio.Event) -> None:
    """Continuously assign queued jobs to providers.

    The whole body (including the Redis dequeue) is guarded: a Redis outage must not crash
    the scheduler. On any error we back off and continue — the DB is the source of truth, so
    the reaper's ``recover_queued_jobs`` sweep re-enqueues anything dropped once Redis is back
    (Session 12.5). No job is lost.
    """
    settings = get_settings()
    factory = get_sessionmaker()
    while not stop.is_set():
        try:
            job_id = await dequeue_job(timeout=2)
            if job_id is None:
                continue
            async with factory() as session:
                provider = await assign_job(session, job_id, settings)
            if provider is None:
                # No provider fit (or already claimed elsewhere) — retry later.
                await asyncio.sleep(_REQUEUE_DELAY_SECONDS)
                await enqueue_job(job_id)
        except Exception:
            # Includes Redis connection errors during an outage. Back off; do not re-enqueue
            # here (Redis may be down) — recovery re-enqueues from the DB.
            logger.exception("assignment loop error; backing off")
            await asyncio.sleep(1.0)


async def _reaper_loop(stop: asyncio.Event) -> None:
    """Reclaim expired leases and drain jobs of unreachable providers.

    Ticks on the shorter of a lease-quarter and the connection timeout so a dropped
    agent's jobs are drained within seconds, not a full lease.
    """
    settings = get_settings()
    factory = get_sessionmaker()
    interval = max(1.0, min(settings.lease_seconds / 4, settings.connection_timeout_seconds / 2))
    while not stop.is_set():
        try:
            # Resolve dead attempts of redundant (K>1) jobs first, so a job the surviving
            # votes already decide is finalized before the job-level reaper looks at it.
            async with factory() as session:
                await reap_expired_attempts(session, settings)
            async with factory() as session:
                requeued = await reap_expired_leases(session, settings)
            async with factory() as session:
                requeued += await drain_unreachable_providers(session, settings)
            # Recover any queued job that missed the Redis queue (e.g. a Redis outage at
            # submit time). Re-enqueue is idempotent — assignment only acts on queued jobs.
            async with factory() as session:
                requeued += await recover_queued_jobs(session)
            for job_id in requeued:
                await enqueue_job(job_id)
        except Exception:
            logger.exception("reaper iteration failed")
        await asyncio.sleep(interval)


async def _canary_loop(stop: asyncio.Event) -> None:
    """Periodically inject a canary job so cheating providers get caught."""
    settings = get_settings()
    factory = get_sessionmaker()
    if settings.canary_rate <= 0:
        return
    # Check roughly once per lease; inject with probability canary_rate each check.
    interval = max(5.0, settings.lease_seconds / 2)
    while not stop.is_set():
        await asyncio.sleep(interval)
        if random.random() >= settings.canary_rate:
            continue
        try:
            async with factory() as session:
                canary = await create_canary_job(session)
                await session.commit()
            await enqueue_job(str(canary.id))
            logger.info("injected canary job {}", canary.id)
        except Exception:
            logger.exception("canary injection failed")


async def main() -> None:
    """Run the scheduler until SIGINT/SIGTERM."""
    configure_logging()
    # Fail fast if secrets are misconfigured — before doing any work.
    init_secrets(get_settings())
    logger.info("GRIDIX scheduler starting")
    # Production uses reputation-weighted, stake-gated matching.
    set_matcher(ReputationMatcher())
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    try:
        await asyncio.gather(_assignment_loop(stop), _reaper_loop(stop), _canary_loop(stop))
    finally:
        await close_redis()
        logger.info("GRIDIX scheduler stopped")


if __name__ == "__main__":
    asyncio.run(main())
