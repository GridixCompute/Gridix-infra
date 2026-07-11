"""Session 12.5 — graceful degradation: Redis outage loses no job, no double-charge."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

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
