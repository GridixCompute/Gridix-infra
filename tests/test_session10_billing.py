"""Session 10 — the developer billing view reflects the double-entry ledger exactly."""

import uuid
from decimal import Decimal

from app.ledger import LedgerAccount, LedgerDirection, Posting, post_transaction
from app.models import Job, JobKind, JobStatus
from app.payments import FiatStub
from conftest import auth, register
from httpx import AsyncClient


async def _run_completed_job(session, developer_id: uuid.UUID, provider_id: uuid.UUID) -> uuid.UUID:
    """Drive one job's money through the real FiatStub: hold → settle → refund → data cost."""
    job = Job(
        developer_id=developer_id,
        kind=JobKind.standard,
        status=JobStatus.completed,
        image_ref="ghcr.io/acme/trainer:latest",
        escrow_amount=10.0,
    )
    session.add(job)
    await session.flush()

    pay = FiatStub()
    await pay.hold_escrow(session, job.id, developer_id, Decimal("10"))
    await pay.settle(
        session, job.id, developer_id, provider_id, cost=Decimal("6"), fee=Decimal("0.15")
    )
    await pay.refund(session, job.id, developer_id, Decimal("4"))
    await post_transaction(
        session,
        [
            Posting(LedgerAccount.developer, LedgerDirection.debit, Decimal("0.5"), developer_id),
            Posting(LedgerAccount.protocol, LedgerDirection.credit, Decimal("0.5")),
        ],
        reason="data_cost",
        job_id=job.id,
    )
    return job.id


async def test_summary_matches_the_ledger(client: AsyncClient, session) -> None:
    dev_id, dev_key = await register(client, "developer", "acme")
    prov_id, _ = await register(client, "provider", "farm")
    await _run_completed_job(session, uuid.UUID(dev_id), uuid.UUID(prov_id))
    await session.commit()

    s = (await client.get("/billing/summary", headers=auth(dev_key))).json()
    assert s["provider_paid"] == 5.85  # cost 6 − fee 0.15
    assert s["protocol_fees"] == 0.15
    assert s["data_costs"] == 0.5
    assert s["total_spent"] == 6.5  # 5.85 + 0.15 + 0.5
    assert s["total_refunded"] == 4.0
    assert s["total_escrowed"] == 10.0
    assert s["total_held"] == 0.0  # 10 held − 6 settled − 4 refunded
    assert s["job_count"] == 1
    assert s["balanced"] is True


async def test_ledger_returns_every_leg(client: AsyncClient, session) -> None:
    dev_id, dev_key = await register(client, "developer", "acme")
    prov_id, _ = await register(client, "provider", "farm")
    await _run_completed_job(session, uuid.UUID(dev_id), uuid.UUID(prov_id))
    await session.commit()

    ledger = (await client.get("/billing/ledger", headers=auth(dev_key))).json()
    # hold(2) + settle(3) + refund(2) + data_cost(2) = 9 legs.
    assert len(ledger) == 9
    assert {r["reason"] for r in ledger} == {"escrow_hold", "settle", "refund", "data_cost"}
    # Each transaction group balances: sum(debit) == sum(credit).
    groups: dict[str, float] = {}
    for r in ledger:
        sign = 1 if r["direction"] == "debit" else -1
        groups[r["entry_group"]] = groups.get(r["entry_group"], 0.0) + sign * r["amount"]
    assert all(abs(delta) < 1e-9 for delta in groups.values())


async def test_billing_is_scoped_and_developer_only(client: AsyncClient, session) -> None:
    dev_id, dev_key = await register(client, "developer", "acme")
    prov_id, prov_key = await register(client, "provider", "farm")
    await _run_completed_job(session, uuid.UUID(dev_id), uuid.UUID(prov_id))
    await session.commit()

    # A different developer sees an empty ledger and zeroed summary.
    _other_id, other_key = await register(client, "developer", "other")
    assert (await client.get("/billing/ledger", headers=auth(other_key))).json() == []
    other_summary = (await client.get("/billing/summary", headers=auth(other_key))).json()
    assert other_summary["total_spent"] == 0.0
    assert other_summary["job_count"] == 0
    assert other_summary["balanced"] is True  # vacuously — no groups

    # Provider keys are rejected from the developer billing view.
    assert (await client.get("/billing/summary", headers=auth(prov_key))).status_code == 403
    assert (await client.get("/billing/ledger", headers=auth(prov_key))).status_code == 403
