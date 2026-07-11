"""Session 7.6 — connection health + drain: exclude silent providers, drain their jobs."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job, drain_unreachable_providers, reap_expired_leases
from app.matcher import CapabilityMatcher
from app.models import Job, JobStatus, Provider
from conftest import auth, make_provider, register
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


def _spec_job() -> Job:
    return Job(image_ref="img", resource_spec={"cpu_cores": 1, "memory_mb": 1000})


async def _set_last_seen(session, pid: str, when: datetime | None) -> None:
    provider = await session.get(Provider, uuid.UUID(pid))
    provider.last_seen = when
    await session.commit()


# ── matcher presence gate ───────────────────────────────────────────────────────
async def test_matcher_excludes_silent_but_not_untracked(client: AsyncClient, session, settings):
    """A provider seen-then-silent is excluded; fresh or never-tracked ones are eligible."""
    pid, _ = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    now = datetime.now(UTC)
    stale = now - timedelta(seconds=settings.connection_timeout_seconds + 10)

    # Never tracked → eligible.
    assert any(str(p.id) == pid for p in await CapabilityMatcher().candidates(session, _spec_job()))

    # Seen then silent → excluded.
    await _set_last_seen(session, pid, stale)
    assert not await CapabilityMatcher().candidates(session, _spec_job())

    # Reconnected (fresh) → eligible again.
    await _set_last_seen(session, pid, now)
    assert any(str(p.id) == pid for p in await CapabilityMatcher().candidates(session, _spec_job()))


# ── drain in-flight jobs of an unreachable provider ─────────────────────────────
async def _submit_and_assign(client: AsyncClient, session, settings) -> tuple[str, uuid.UUID]:
    pid, _ = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    _dev, dev_key = await register(client, "developer", "acme")
    r = await client.post("/jobs", headers=auth(dev_key), json={"image_ref": "img"})
    job_id = uuid.UUID(r.json()["id"])
    provider = await assign_job(session, job_id, settings)
    assert provider is not None
    return pid, job_id


async def test_drain_reclaims_before_lease_expiry(client: AsyncClient, session, settings):
    """A silent provider's job is drained immediately, without waiting for the lease."""
    pid, job_id = await _submit_and_assign(client, session, settings)
    # Lease is still set (not expired — proven below by the reaper finding nothing)...
    job = await session.get(Job, job_id)
    assert job.lease_expires_at is not None
    # ...but the provider went silent.
    await _set_last_seen(
        session, pid, datetime.now(UTC) - timedelta(seconds=settings.connection_timeout_seconds + 5)
    )

    # Lease-based reaper does nothing yet; drain reclaims the job.
    assert await reap_expired_leases(session, settings) == []
    requeued = await drain_unreachable_providers(session, settings)
    assert str(job_id) in requeued

    reclaimed = await session.get(Job, job_id)
    await session.refresh(reclaimed)
    assert reclaimed.status is JobStatus.queued
    assert reclaimed.assigned_provider_id is None


async def test_drain_fails_job_after_max_attempts(client: AsyncClient, session, settings):
    pid, job_id = await _submit_and_assign(client, session, settings)
    job = await session.get(Job, job_id)
    job.attempt_count = settings.max_attempts
    await session.commit()
    await _set_last_seen(
        session, pid, datetime.now(UTC) - timedelta(seconds=settings.connection_timeout_seconds + 5)
    )

    assert await drain_unreachable_providers(session, settings) == []
    failed = await session.get(Job, job_id)
    await session.refresh(failed)
    assert failed.status is JobStatus.failed


async def test_silent_provider_gets_no_new_work_until_reconnect(client, session, settings):
    """After going silent a provider is passed over; reconnecting makes it eligible again."""
    pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    _dev, dev_key = await register(client, "developer", "acme")
    await _set_last_seen(
        session, pid, datetime.now(UTC) - timedelta(seconds=settings.connection_timeout_seconds + 5)
    )

    r = await client.post("/jobs", headers=auth(dev_key), json={"image_ref": "img"})
    job_id = uuid.UUID(r.json()["id"])
    assert await assign_job(session, job_id, settings) is None  # no reachable provider

    # Reconnect via the keepalive endpoint (refreshes last_seen), then it can be assigned.
    assert (await client.post("/agent/ping", headers=auth(prov_key))).json()["connected"] is True
    provider = await assign_job(session, job_id, settings)
    assert provider is not None and str(provider.id) == pid
