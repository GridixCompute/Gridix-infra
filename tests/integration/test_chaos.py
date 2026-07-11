"""Session 12.8 — chaos: node churn + reassignment, asserting the two invariants.

Invariant 1: no job is silently lost — every job ends terminal.
Invariant 2: the ledger stays balanced under all the churn.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job, drain_unreachable_providers, recover_queued_jobs
from app.ledger import verify_ledger_integrity
from app.models import Job, JobStatus, Provider
from app.results import record_result
from app.schemas import AgentResultRequest
from app.state_machine import TERMINAL_STATES
from conftest import auth, make_provider, register
from httpx import AsyncClient
from sqlalchemy import select

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


async def _complete_running(session, settings) -> None:
    """Complete every assigned/running job via its assigned provider."""
    jobs = list(
        await session.scalars(
            select(Job).where(Job.status.in_((JobStatus.assigned, JobStatus.running)))
        )
    )
    for job in jobs:
        provider = await session.get(Provider, job.assigned_provider_id)
        h = job.id.hex + job.id.hex  # a deterministic 64-char output hash
        await record_result(
            session,
            job,
            provider,
            AgentResultRequest(
                result_ref=h, exit_code=0, proof={"output_sha256": h, "exit_code": 0}
            ),
            settings,
        )
    await session.commit()


async def test_churn_loses_no_job_and_keeps_ledger_balanced(client: AsyncClient, session, settings):
    # --- setup: all HTTP writes first (providers + jobs) ---
    provider_ids = []
    for i in range(6):
        pid, _ = await make_provider(
            client, f"p{i}", cpu_cores=8, memory_mb=64000, max_concurrent=20
        )
        provider_ids.append(uuid.UUID(pid))
    _dev, dev_key = await register(client, "developer", "acme")
    job_ids = []
    for _ in range(18):
        r = await client.post(
            "/jobs",
            headers=auth(dev_key),
            json={"image_ref": "img", "resource_spec": {"cpu_cores": 1, "memory_mb": 1000}},
        )
        job_ids.append(uuid.UUID(r.json()["id"]))

    # --- assign everything ---
    for jid in job_ids:
        await assign_job(session, jid, settings)

    # --- chaos: 3 of 6 nodes drop (go silent); drain reassigns their in-flight jobs ---
    stale = datetime.now(UTC) - timedelta(seconds=settings.connection_timeout_seconds + 5)
    for pid in provider_ids[:3]:
        p = await session.get(Provider, pid)
        p.last_seen = stale
    await session.commit()
    await drain_unreachable_providers(session, settings)

    # Re-enqueue + reassign the recovered jobs to the survivors, over a couple of rounds.
    for _ in range(3):
        queued = await recover_queued_jobs(session)
        for jid in queued:
            await assign_job(session, jid, settings)
        await _complete_running(session, settings)

    # --- invariants ---
    session.expire_all()
    final = list(await session.scalars(select(Job)))
    real_jobs = [j for j in final if j.id in set(job_ids)]
    assert len(real_jobs) == 18
    # Invariant 1: no job silently lost — every job is terminal.
    assert all(j.status in TERMINAL_STATES for j in real_jobs), [
        (str(j.id), j.status) for j in real_jobs if j.status not in TERMINAL_STATES
    ]
    assert all(j.status is JobStatus.completed for j in real_jobs)
    # Invariant 2: the ledger stays balanced through all the churn.
    assert await verify_ledger_integrity(session) == []
