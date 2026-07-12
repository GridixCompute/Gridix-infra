"""Session 12.5 — graceful degradation: Redis outage loses no job, no double-charge."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import recover_queued_jobs
from app.ledger import LedgerAccount, account_balance
from app.models import Job, JobStatus
from conftest import auth, register
from httpx import AsyncClient


async def test_redis_outage_persists_job_and_does_not_double_charge(
    client: AsyncClient, session
) -> None:
    """Submitting while Redis is down still persists the job and escrows exactly once."""
    dev_id, dev_key = await register(client, "developer", "acme")

    # Redis enqueue raises (simulated outage) — submit must still succeed.
    with patch(
        "app.routes.jobs.enqueue_job", new=AsyncMock(side_effect=ConnectionError("redis down"))
    ):
        resp = await client.post(
            "/jobs",
            headers=auth(dev_key),
            json={"image_ref": "img", "resource_spec": {"cpu_cores": 1, "memory_mb": 1000}},
        )
    assert resp.status_code == 201
    job_id = uuid.UUID(resp.json()["id"])

    # The job is persisted as queued (not lost).
    job = await session.get(Job, job_id)
    assert job.status is JobStatus.queued

    # Escrow was held exactly once — the failed enqueue did not double-charge.
    escrow = Decimal(str(resp.json()["escrow_amount"]))
    assert await account_balance(session, LedgerAccount.escrow, uuid.UUID(dev_id)) == escrow

    # The recovery sweep finds it for re-enqueue → no job lost.
    recovered = await recover_queued_jobs(session)
    assert str(job_id) in recovered


async def test_recovery_is_idempotent_over_queued_jobs(client: AsyncClient, session) -> None:
    _dev, dev_key = await register(client, "developer", "acme")
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        ids = {
            (await client.post("/jobs", headers=auth(dev_key), json={"image_ref": "i"})).json()[
                "id"
            ]
            for _ in range(3)
        }
    recovered = set(await recover_queued_jobs(session))
    assert ids <= recovered  # every queued job is recoverable


async def test_assignment_loop_survives_redis_outage() -> None:
    """A Redis error from dequeue must NOT crash the scheduler's assignment loop — it backs
    off and keeps running, so the reaper's recovery sweep can re-enqueue once Redis is back.
    (Regression: an unguarded dequeue previously took the whole scheduler down under churn.)"""
    import asyncio

    from app.scheduler import _assignment_loop

    stop = asyncio.Event()
    calls = 0

    async def boom(*_a, **_k):
        nonlocal calls
        calls += 1
        if calls >= 3:
            stop.set()
        raise ConnectionError("redis down")

    with patch("app.scheduler.dequeue_job", new=boom):
        # Returns (does not raise) despite dequeue failing every time.
        await asyncio.wait_for(_assignment_loop(stop), timeout=10)
    assert calls >= 3


def test_boot_rejected_when_timeout_not_above_twice_heartbeat() -> None:
    """The liveness invariant is enforced at config load, not just documented: a
    connection_timeout that doesn't clear 2x the heartbeat refuses to boot. This is the
    config interaction that spuriously reassigned a long-running job (double-run + container
    collision) — the kind of bug two individually-reasonable settings create, so the code has
    to forbid it."""
    from app.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError):  # 12 <= 2*10
        Settings(connection_timeout_seconds=12, agent_heartbeat_interval_seconds=10)
    with pytest.raises(ValidationError):  # boundary: 20 <= 2*10
        Settings(connection_timeout_seconds=20, agent_heartbeat_interval_seconds=10)
    # A config with headroom constructs fine (30 > 2*10).
    ok = Settings(connection_timeout_seconds=30, agent_heartbeat_interval_seconds=10)
    assert ok.connection_timeout_seconds == 30
