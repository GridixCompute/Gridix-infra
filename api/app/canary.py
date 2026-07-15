"""Canary jobs — known-answer work injected to catch cheating providers.

A canary is indistinguishable from a real job to a provider, but the coordinator already
knows its correct output hash. The scheduler injects canaries at ``canary_rate``; when a
provider returns the wrong answer, verification lowers its reputation and slashes it. Over
time this makes returning garbage instead of doing the work a losing strategy.

Canaries are owned by a dedicated system developer (they are internal, not billed to any
customer). The canonical canary is a tiny deterministic image whose output hash is fixed.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Developer, Job, JobKind, JobStatus

# Canonical canary definition. In production this is a small deterministic image whose
# output (for the given input) is fixed; the hash below is that known-good sha256.
CANARY_IMAGE = "ghcr.io/gridix/canary:1"
CANARY_EXPECTED_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_SYSTEM_DEVELOPER_NAME = "__gridix_system__"
# Fixed id for the canary-owning system developer (security wave 0 / H12). Canary ownership
# is keyed on THIS id, never on the name — so registering a look-alike name cannot hijack
# canaries. Registration also refuses the reserved ``__gridix_`` prefix (see routes).
SYSTEM_DEVELOPER_ID = uuid.UUID("00000000-0000-0000-0000-00000000c0de")


async def _system_developer(session: AsyncSession) -> Developer:
    """Return (creating if needed) the internal developer that owns canaries, by fixed id."""
    dev = await session.get(Developer, SYSTEM_DEVELOPER_ID)
    if dev is None:
        dev = Developer(id=SYSTEM_DEVELOPER_ID, name=_SYSTEM_DEVELOPER_NAME)
        session.add(dev)
        await session.flush()
    return dev


async def create_canary_job(session: AsyncSession) -> Job:
    """Create and persist a queued canary job. Returns the job (id available)."""
    dev = await _system_developer(session)
    job = Job(
        developer_id=dev.id,
        kind=JobKind.canary,
        status=JobStatus.queued,
        image_ref=CANARY_IMAGE,
        resource_spec={"cpu_cores": 1, "memory_mb": 512},
        timeout_seconds=120,
        expected_output_hash=CANARY_EXPECTED_HASH,
    )
    job.queued_at = job.created_at
    session.add(job)
    await session.flush()
    return job


async def is_canary(session: AsyncSession, job_id: uuid.UUID) -> bool:
    """Whether a job id refers to a canary."""
    kind = await session.scalar(select(Job.kind).where(Job.id == job_id))
    return kind is JobKind.canary
