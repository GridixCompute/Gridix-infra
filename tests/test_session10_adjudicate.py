"""Session 10.3 — automated re-check: clear cases resolve, ambiguous escalates."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.adjudicate import auto_adjudicate
from app.assignment import assign_job
from app.canary import create_canary_job
from app.disputes import open_dispute
from app.ledger import LedgerAccount, account_balance, deposit_stake, provider_stake
from app.models import Dispute, DisputeState, Job, Provider
from app.results import record_result
from app.schemas import AgentResultRequest
from conftest import make_provider
from sqlalchemy import select

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


async def test_clearly_wrong_result_auto_upholds(client, session, settings) -> None:
    pid, _ = await make_provider(client, "cheat", cpu_cores=8, memory_mb=16000)
    puid = uuid.UUID(pid)
    await deposit_stake(session, puid, Decimal(settings.min_provider_stake))
    canary = await create_canary_job(session)
    await session.commit()
    await assign_job(session, canary.id, settings)
    job = await session.get(Job, canary.id)
    provider = await session.get(Provider, puid)
    await record_result(
        session,
        job,
        provider,
        AgentResultRequest(result_ref="x", exit_code=0, proof={"output_sha256": "wrong"}),
        settings,
    )
    await session.commit()

    dispute = await session.scalar(select(Dispute).where(Dispute.provider_id == puid))
    outcome = await auto_adjudicate(session, dispute, settings)
    assert outcome is DisputeState.upheld
    assert await account_balance(session, LedgerAccount.disputed, puid) == Decimal(0)  # burned


async def test_clearly_correct_result_auto_overturns(client, session, settings) -> None:
    pid, _ = await make_provider(client, "honest", cpu_cores=8, memory_mb=16000)
    puid = uuid.UUID(pid)
    await deposit_stake(session, puid, Decimal(100))
    # A mistaken slash: the submitted output actually matched the known-good answer.
    dispute = await open_dispute(
        session, puid, Decimal(50), reason="canary_fail", settings=settings
    )
    dispute.evidence = {"expected_output_hash": "abc", "submitted_output_hash": "abc"}

    outcome = await auto_adjudicate(session, dispute, settings)
    assert outcome is DisputeState.overturned
    assert await provider_stake(session, puid) == Decimal(100)  # made whole


async def test_ambiguous_result_escalates(client, session, settings) -> None:
    pid, _ = await make_provider(client, "p", cpu_cores=8, memory_mb=16000)
    puid = uuid.UUID(pid)
    await deposit_stake(session, puid, Decimal(100))
    dispute = await open_dispute(session, puid, Decimal(50), reason="quorum", settings=settings)
    dispute.evidence = {"submitted_output_hash": None, "quorum_votes": []}

    outcome = await auto_adjudicate(session, dispute, settings)
    assert outcome is None
    assert dispute.state is DisputeState.under_review  # escalated, funds still held
    assert await account_balance(session, LedgerAccount.disputed, puid) == Decimal(50)
