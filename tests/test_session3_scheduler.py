"""Session 3 — scheduler assignment, agent protocol, leases, and the reaper."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job, reap_expired_leases
from app.matcher import CapabilityMatcher
from app.models import Job, JobAttempt, JobStatus
from conftest import auth, make_provider, register
from httpx import AsyncClient
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


async def _submit(client: AsyncClient, dev_key: str, **spec) -> uuid.UUID:
    body = {"image_ref": "img", "resource_spec": spec} if spec else {"image_ref": "img"}
    r = await client.post("/jobs", headers=auth(dev_key), json=body)
    assert r.status_code == 201, r.text
    return uuid.UUID(r.json()["id"])


async def test_scheduler_assigns_to_capable_provider(
    client: AsyncClient, session, settings
) -> None:
    """A queued job is assigned to a provider that satisfies its spec, with a lease."""
    pid, _ = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000, max_concurrent=2)
    _dev, dev_key = await register(client, "developer", "Acme")
    job_id = await _submit(client, dev_key, cpu_cores=4, memory_mb=8000)

    provider = await assign_job(session, job_id, settings)
    assert provider is not None and str(provider.id) == pid

    job = await session.get(Job, job_id)
    await session.refresh(job)
    assert job.status is JobStatus.assigned
    assert str(job.assigned_provider_id) == pid
    assert job.lease_expires_at is not None
    assert job.attempt_count == 1

    attempt = await session.scalar(select(JobAttempt).where(JobAttempt.job_id == job.id))
    assert attempt is not None and attempt.attempt_number == 1


async def test_no_capable_provider_leaves_job_queued(
    client: AsyncClient, session, settings
) -> None:
    """A job needing a GPU finds no CPU-only provider and is not assigned."""
    await make_provider(client, "cpu-only", cpu_cores=8, memory_mb=16000)
    _dev, dev_key = await register(client, "developer", "Acme")
    job_id = await _submit(client, dev_key, gpu=True, gpu_vram_mb=8000, cpu_cores=1)

    provider = await assign_job(session, job_id, settings)
    assert provider is None
    job = await session.get(Job, job_id)
    assert job.status is JobStatus.queued


async def test_matcher_picks_least_loaded(client: AsyncClient, session) -> None:
    """Given two capable providers, the one with spare capacity is chosen."""
    busy, _ = await make_provider(client, "busy", cpu_cores=8, memory_mb=16000, max_concurrent=1)
    free, _ = await make_provider(client, "free", cpu_cores=8, memory_mb=16000, max_concurrent=1)
    _dev, dev_key = await register(client, "developer", "Acme")

    # Occupy `busy` with a running job so it is at capacity.
    busy_job = await _submit(client, dev_key, cpu_cores=1, memory_mb=1000)
    job = await session.get(Job, busy_job)
    job.status = JobStatus.running
    job.assigned_provider_id = uuid.UUID(busy)
    await session.commit()

    target = await _submit(client, dev_key, cpu_cores=1, memory_mb=1000)
    chosen = await CapabilityMatcher().select(session, await session.get(Job, target))
    assert chosen is not None and str(chosen.id) == free


async def test_agent_poll_heartbeat_and_running(client: AsyncClient, session, settings) -> None:
    """Agent polls its assigned job, reports running, and extends its lease."""
    pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    _dev, dev_key = await register(client, "developer", "Acme")
    job_id = await _submit(client, dev_key, cpu_cores=1, memory_mb=1000)
    await assign_job(session, job_id, settings)

    polled = await client.post("/agent/poll", headers=auth(prov_key))
    assert polled.status_code == 200
    assert polled.json()["job"]["id"] == str(job_id)

    started = await client.post(
        f"/agent/jobs/{job_id}/status", headers=auth(prov_key), json={"status": "running"}
    )
    assert started.status_code == 200
    assert started.json()["status"] == JobStatus.running

    hb = await client.post("/agent/heartbeat", headers=auth(prov_key), json={"job_id": str(job_id)})
    assert hb.status_code == 200
    assert hb.json()["lease_expires_at"] is not None

    # After running, poll returns empty (no more assigned jobs).
    assert (await client.post("/agent/poll", headers=auth(prov_key))).json()["job"] is None


async def test_expired_lease_is_reassigned(client: AsyncClient, session, settings) -> None:
    """A silent provider's job (expired lease) is requeued for another attempt."""
    await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    _dev, dev_key = await register(client, "developer", "Acme")
    job_id = await _submit(client, dev_key, cpu_cores=1, memory_mb=1000)
    await assign_job(session, job_id, settings)

    # Force the lease into the past.
    job = await session.get(Job, job_id)
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()

    requeued = await reap_expired_leases(session, settings)
    assert str(job_id) in requeued
    reclaimed = await session.get(Job, job_id)
    await session.refresh(reclaimed)
    assert reclaimed.status is JobStatus.queued
    assert reclaimed.assigned_provider_id is None


async def test_job_fails_after_max_attempts(client: AsyncClient, session, settings) -> None:
    """Once the attempt budget is spent, an expired lease ends the job in `failed`."""
    await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    _dev, dev_key = await register(client, "developer", "Acme")
    job_id = await _submit(client, dev_key, cpu_cores=1, memory_mb=1000)
    await assign_job(session, job_id, settings)

    job = await session.get(Job, job_id)
    job.attempt_count = settings.max_attempts  # budget exhausted
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()

    requeued = await reap_expired_leases(session, settings)
    assert requeued == []
    failed = await session.get(Job, job_id)
    await session.refresh(failed)
    assert failed.status is JobStatus.failed
