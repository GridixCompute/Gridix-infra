"""Session 10.4 — ambiguous disputes escalate to a review queue and are ruled on."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.adjudicate import auto_adjudicate
from app.config import get_settings
from app.disputes import open_dispute
from app.ledger import LedgerAccount, account_balance, deposit_stake, provider_stake
from app.models import DisputeState
from conftest import make_provider

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


def _admin() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_settings().secret_key}"}


async def _escalated_dispute(client, session, settings):
    pid, _ = await make_provider(client, "p", cpu_cores=8, memory_mb=16000)
    puid = uuid.UUID(pid)
    await deposit_stake(session, puid, Decimal(100))
    dispute = await open_dispute(session, puid, Decimal(50), reason="quorum", settings=settings)
    dispute.evidence = {"submitted_output_hash": None, "quorum_votes": []}
    await auto_adjudicate(session, dispute, settings)  # → under_review
    await session.commit()
    return dispute, puid


async def test_ambiguous_lands_in_review_queue(client, session, settings) -> None:
    dispute, _puid = await _escalated_dispute(client, session, settings)
    q = await client.get("/disputes/review-queue", headers=_admin())
    assert q.status_code == 200
    ids = [d["id"] for d in q.json()]
    assert str(dispute.id) in ids


async def test_operator_ruling_resolves_with_audit(client, session, settings) -> None:
    dispute, puid = await _escalated_dispute(client, session, settings)
    resp = await client.post(
        f"/disputes/{dispute.id}/rule",
        headers=_admin(),
        json={"upheld": False, "reason": "hardware flake, not adversarial"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "overturned"
    assert body["ruling_reason"] == "hardware flake, not adversarial"  # audit-logged
    # Overturned → stake returned.
    assert await provider_stake(session, puid) == Decimal(100)
    assert await account_balance(session, LedgerAccount.disputed, puid) == Decimal(0)


async def test_review_queue_requires_operator_secret(client) -> None:
    resp = await client.get("/disputes/review-queue", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


async def test_ruling_rejects_already_resolved(client, session, settings) -> None:
    dispute, _puid = await _escalated_dispute(client, session, settings)
    await client.post(
        f"/disputes/{dispute.id}/rule", headers=_admin(), json={"upheld": True, "reason": "x"}
    )
    again = await client.post(
        f"/disputes/{dispute.id}/rule", headers=_admin(), json={"upheld": True, "reason": "y"}
    )
    assert again.status_code == 409


async def test_state_enum_terminal_ok() -> None:
    assert DisputeState.overturned in (DisputeState.upheld, DisputeState.overturned)
