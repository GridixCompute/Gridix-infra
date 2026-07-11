"""Session 12.4 — DR: ledger integrity check confirms zero discrepancy after restore."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job
from app.ledger import (
    LedgerAccount,
    LedgerDirection,
    Posting,
    deposit_stake,
    post_transaction,
    verify_ledger_integrity,
)
from app.models import LedgerEntry
from app.storage import content_digest
from conftest import auth, make_provider, register

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


async def test_balanced_ledger_has_zero_discrepancy(client, session, settings) -> None:
    """After a full escrow→settle flow, every transaction group balances."""
    pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    await deposit_stake(session, uuid.UUID(pid), Decimal(100))
    await session.commit()
    _dev, dev_key = await register(client, "developer", "acme")

    r = await client.post(
        "/jobs",
        headers=auth(dev_key),
        json={"image_ref": "img", "resource_spec": {"cpu_cores": 2, "memory_mb": 1000}},
    )
    job_id = uuid.UUID(r.json()["id"])
    await assign_job(session, job_id, settings)
    await client.post(
        f"/agent/jobs/{job_id}/status", headers=auth(prov_key), json={"status": "running"}
    )
    out = b"result"
    up = await client.post(
        "/agent/blobs",
        headers=auth(prov_key),
        files={"file": ("r", out, "application/octet-stream")},
    )
    await client.post(
        f"/agent/jobs/{job_id}/result",
        headers=auth(prov_key),
        json={
            "result_ref": up.json()["ref"],
            "exit_code": 0,
            "proof": {"output_sha256": content_digest(out), "exit_code": 0},
            "timed_out": False,
        },
    )

    # The invariant that a DR restore must preserve.
    assert await verify_ledger_integrity(session) == []


async def test_integrity_check_detects_unbalanced_group(session) -> None:
    """A corrupted (unbalanced) transaction group is detected."""
    # A balanced posting is fine.
    await deposit_stake(session, uuid.uuid4(), Decimal(10))
    assert await verify_ledger_integrity(session) == []

    # Simulate a torn write: a lone debit with no matching credit.
    session.add(
        LedgerEntry(
            entry_group=uuid.uuid4(),
            account=LedgerAccount.protocol,
            direction=LedgerDirection.debit,
            amount=Decimal(5),
            reason="torn",
        )
    )
    await session.flush()
    discrepancies = await verify_ledger_integrity(session)
    assert len(discrepancies) == 1 and discrepancies[0][1] == Decimal(5)


async def test_post_transaction_stays_balanced(session) -> None:
    await post_transaction(
        session,
        [
            Posting(LedgerAccount.protocol, LedgerDirection.debit, Decimal(7)),
            Posting(LedgerAccount.stake, LedgerDirection.credit, Decimal(7), uuid.uuid4()),
        ],
        reason="t",
    )
    assert await verify_ledger_integrity(session) == []
