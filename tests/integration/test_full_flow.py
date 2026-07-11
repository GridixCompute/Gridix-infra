"""Integration — the full job lifecycle and escrow correctness.

Covers the happy path (submit → escrow → assign → run → verify → settle) and the timeout
failure path (→ refund), asserting the money invariants the whole design hinges on:
a developer is charged only for verified work, a provider is paid only net of fee for
verified work, and a failed job refunds the developer and pays no one.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job
from app.ledger import account_balance, deposit_stake, provider_stake
from app.models import Job, JobStatus, LedgerAccount
from app.pricing import protocol_fee
from conftest import auth, make_provider, register
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


def _result_body(hash_: str | None, *, exit_code: int = 0, timed_out: bool = False) -> dict:
    proof = {"exit_code": exit_code}
    if hash_ is not None:
        proof["output_sha256"] = hash_
    return {"result_ref": hash_, "exit_code": exit_code, "proof": proof, "timed_out": timed_out}


async def test_happy_path_settles_correctly(client: AsyncClient, session, settings) -> None:
    """submit → assign → run → complete → settle, with exact ledger balances."""
    dev_id, dev_key = await register(client, "developer", "Acme")
    prov_id, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    await deposit_stake(session, uuid.UUID(prov_id), Decimal(settings.min_provider_stake))
    await session.commit()

    # 2 cores, 300s timeout → escrow = 1 × 2 × 5min = 10.
    submit = await client.post(
        "/jobs",
        headers=auth(dev_key),
        json={"image_ref": "img", "resource_spec": {"cpu_cores": 2, "memory_mb": 1000}},
    )
    job_id = uuid.UUID(submit.json()["id"])
    assert Decimal(str(submit.json()["escrow_amount"])) == Decimal("10")
    # Developer debited into escrow at submit.
    assert await account_balance(session, LedgerAccount.escrow, uuid.UUID(dev_id)) == Decimal("10")

    await assign_job(session, job_id, settings)
    await client.post(
        f"/agent/jobs/{job_id}/status", headers=auth(prov_key), json={"status": "running"}
    )

    # Backdate the start so the run bills a real 120s (2 minutes → cost 4).
    job = await session.get(Job, job_id)
    job.started_at = datetime.now(UTC) - timedelta(seconds=120)
    await session.commit()

    output_hash = "a" * 64
    res = await client.post(
        f"/agent/jobs/{job_id}/result", headers=auth(prov_key), json=_result_body(output_hash)
    )
    assert res.json()["status"] == JobStatus.completed

    # The billed duration is ~120s; assert the exact escrow invariants against cost_final
    # (jitter of a few ms makes the absolute figure ~4.00, so pin the relationships).
    session.expire_all()  # the API updated the job in its own session; drop stale cache
    final = await session.get(Job, job_id)
    cost = Decimal(str(final.cost_final))
    fee = protocol_fee(cost, settings)
    assert Decimal("4") <= cost < Decimal("4.05")  # ~2 cpu-minutes

    dev_bal = await account_balance(session, LedgerAccount.developer, uuid.UUID(dev_id))
    prov_bal = await account_balance(session, LedgerAccount.provider, uuid.UUID(prov_id))
    escrow_bal = await account_balance(session, LedgerAccount.escrow, uuid.UUID(dev_id))
    # Developer pays exactly the cost; provider receives cost minus fee; escrow empties.
    assert dev_bal == -cost
    assert prov_bal == cost - fee
    assert escrow_bal == Decimal("0")


async def test_timeout_refunds_developer_and_pays_no_one(
    client: AsyncClient, session, settings
) -> None:
    """A timed-out job refunds the full escrow and pays no provider."""
    dev_id, dev_key = await register(client, "developer", "Acme")
    prov_id, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    await deposit_stake(session, uuid.UUID(prov_id), Decimal(settings.min_provider_stake))
    await session.commit()

    submit = await client.post(
        "/jobs",
        headers=auth(dev_key),
        json={"image_ref": "img", "resource_spec": {"cpu_cores": 1, "memory_mb": 1000}},
    )
    job_id = uuid.UUID(submit.json()["id"])
    escrow = Decimal(str(submit.json()["escrow_amount"]))

    await assign_job(session, job_id, settings)
    await client.post(
        f"/agent/jobs/{job_id}/status", headers=auth(prov_key), json={"status": "running"}
    )
    res = await client.post(
        f"/agent/jobs/{job_id}/result",
        headers=auth(prov_key),
        json=_result_body(None, exit_code=124, timed_out=True),
    )
    assert res.json()["status"] == JobStatus.timeout

    # Developer made whole; provider paid nothing; stake untouched (honest failure).
    assert await account_balance(session, LedgerAccount.developer, uuid.UUID(dev_id)) == Decimal(
        "0"
    )
    assert await account_balance(session, LedgerAccount.provider, uuid.UUID(prov_id)) == Decimal(
        "0"
    )
    assert await account_balance(session, LedgerAccount.escrow, uuid.UUID(dev_id)) == Decimal("0")
    assert await provider_stake(session, uuid.UUID(prov_id)) == Decimal(settings.min_provider_stake)
    assert escrow > 0


async def test_audit_trail_records_lifecycle(client: AsyncClient, session, settings) -> None:
    """The audit endpoint returns attempts and ledger movements for a job."""
    dev_id, dev_key = await register(client, "developer", "Acme")
    prov_id, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    await deposit_stake(session, uuid.UUID(prov_id), Decimal(settings.min_provider_stake))
    await session.commit()

    submit = await client.post("/jobs", headers=auth(dev_key), json={"image_ref": "img"})
    job_id = uuid.UUID(submit.json()["id"])
    await assign_job(session, job_id, settings)
    await client.post(
        f"/agent/jobs/{job_id}/status", headers=auth(prov_key), json={"status": "running"}
    )
    await client.post(
        f"/agent/jobs/{job_id}/result", headers=auth(prov_key), json=_result_body("b" * 64)
    )

    audit = await client.get(f"/jobs/{job_id}/audit", headers=auth(dev_key))
    assert audit.status_code == 200
    body = audit.json()
    assert len(body["attempts"]) == 1
    # Escrow hold + settlement/refund postings are present.
    reasons = {row["reason"] for row in body["ledger"]}
    assert "escrow_hold" in reasons
