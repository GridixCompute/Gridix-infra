"""Job assignment and lease reaping — the reliability core.

Assignment is concurrency-safe: the job row is locked with ``FOR UPDATE SKIP LOCKED``
(a no-op on SQLite, honored on Postgres) and its status re-checked inside the
transaction, so two schedulers can never assign the same job twice. The reaper reclaims
jobs whose lease lapsed and fails them once they exhaust their attempt budget.
"""

import uuid
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.matcher import get_matcher
from app.models import AttemptOutcome, Job, JobAttempt, JobStatus, Provider
from app.state_machine import transition


def _now() -> datetime:
    return datetime.now(UTC)


async def assign_job(
    session: AsyncSession, job_id: str | uuid.UUID, settings: Settings
) -> Provider | None:
    """Attempt to assign one queued job. Returns the primary provider, or None.

    Normal jobs go to one provider. A high-value job with redundancy K is assigned to up
    to K distinct providers in one round (one attempt each) so their results can be
    cross-checked by quorum. ``attempt_count`` counts *rounds* (the retry budget the
    reaper enforces), while each attempt gets a unique, monotonic ``attempt_number``.
    """
    providers = await assign_providers(session, job_id, settings)
    return providers[0] if providers else None


async def assign_providers(
    session: AsyncSession, job_id: str | uuid.UUID, settings: Settings
) -> list[Provider]:
    """Assign a queued job to its providers (1, or K for redundant jobs). Returns them."""
    # The scheduler dequeues ids as strings from Redis; the DB needs real UUIDs.
    job_uuid = uuid.UUID(str(job_id))
    job = await session.scalar(
        select(Job).where(Job.id == job_uuid).with_for_update(skip_locked=True)
    )
    if job is None or job.status is not JobStatus.queued:
        return []

    want = job.redundancy if job.is_high_value else 1
    candidates = await get_matcher().candidates(session, job)
    providers = candidates[:want]
    if not providers:
        return []

    lease = _now() + timedelta(seconds=settings.lease_seconds)
    transition(job, JobStatus.assigned)
    job.assigned_provider_id = providers[0].id
    job.lease_expires_at = lease
    job.attempt_count += 1  # one assignment round

    base = await session.scalar(
        select(func.coalesce(func.max(JobAttempt.attempt_number), 0)).where(
            JobAttempt.job_id == job.id
        )
    )
    for idx, provider in enumerate(providers, start=1):
        session.add(
            JobAttempt(
                job_id=job.id,
                provider_id=provider.id,
                attempt_number=(base or 0) + idx,
                outcome=AttemptOutcome.assigned,
                lease_expires_at=lease,
            )
        )
    await session.commit()
    logger.info(
        "assigned job {} → {} provider(s) (round {})",
        job.id,
        len(providers),
        job.attempt_count,
    )
    return providers


async def reap_expired_leases(session: AsyncSession, settings: Settings) -> list[str]:
    """Reclaim jobs whose lease expired without progress.

    Each reclaimed job is requeued (``→ queued``) unless it has exhausted
    ``max_attempts``, in which case it is failed. Returns the list of job ids that were
    requeued so the caller can push them back onto the Redis queue.
    """
    now = _now()
    stale = await session.scalars(
        select(Job)
        .where(
            Job.status.in_((JobStatus.assigned, JobStatus.running)),
            Job.lease_expires_at.is_not(None),
            Job.lease_expires_at < now,
        )
        .with_for_update(skip_locked=True)
    )

    requeued: list[str] = []
    for job in stale:
        # Close the in-flight attempt as reassigned/timed-out.
        attempt = await session.scalar(
            select(JobAttempt)
            .where(JobAttempt.job_id == job.id)
            .order_by(JobAttempt.attempt_number.desc())
            .limit(1)
        )
        if attempt is not None and attempt.finished_at is None:
            attempt.finished_at = now

        if job.attempt_count >= settings.max_attempts:
            if attempt is not None:
                attempt.outcome = AttemptOutcome.failed
            transition(job, JobStatus.failed)
            logger.warning("job {} failed after {} attempts", job.id, job.attempt_count)
        else:
            if attempt is not None:
                attempt.outcome = AttemptOutcome.reassigned
            transition(job, JobStatus.queued)
            requeued.append(str(job.id))
            logger.info("job {} lease expired → requeued (attempt {})", job.id, job.attempt_count)

    await session.commit()
    return requeued
