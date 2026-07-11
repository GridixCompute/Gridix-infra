"""Session 10.1 — dispute lifecycle: slashes are held, not burned, pending resolution."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job
from app.canary import create_canary_job
from app.disputes import open_dispute, resolve_dispute
from app.ledger import LedgerAccount, account_balance, deposit_stake, provider_stake
from app.models import Dispute, DisputeState, Job
from app.results import record_result
from app.schemas import AgentResultRequest
from conftest import make_provider
from sqlalchemy import select

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


# ── hold + resolve unit ─────────────────────────────────────────────────────────
async def test_slash_holds_then_upheld_burns(client, session, settings) -> None:
    pid, _ = await make_provider(client, "p", cpu_cores=8, memory_mb=16000)
    puid = uuid.UUID(pid)
    await deposit_stake(session, puid, Decimal(100))

    dispute = await open_dispute(
        session, puid, Decimal(50), reason="canary_fail", settings=settings
    )
    # Held, not burned: stake down, disputed up, dispute open.
    assert await provider_stake(session, puid) == Decimal(50)
    assert await account_balance(session, LedgerAccount.disputed, puid) == Decimal(50)
    assert dispute.state is DisputeState.open

    await resolve_dispute(session, dispute, upheld=True, ruling_reason="clearly wrong")
    assert dispute.state is DisputeState.upheld
    assert await account_balance(session, LedgerAccount.disputed, puid) == Decimal(0)
    assert await provider_stake(session, puid) == Decimal(50)  # burned, not returned


async def test_overturned_returns_stake(client, session, settings) -> None:
    pid, _ = await make_provider(client, "p", cpu_cores=8, memory_mb=16000)
    puid = uuid.UUID(pid)
    await deposit_stake(session, puid, Decimal(100))
    dispute = await open_dispute(session, puid, Decimal(50), reason="quorum", settings=settings)

    await resolve_dispute(session, dispute, upheld=False, ruling_reason="provider was right")
    assert dispute.state is DisputeState.overturned
    assert await account_balance(session, LedgerAccount.disputed, puid) == Decimal(0)
    assert await provider_stake(session, puid) == Decimal(100)  # made whole


# ── canary failure opens a held dispute (no immediate burn) ──────────────────────
async def test_canary_failure_opens_dispute_and_holds(client, session, settings) -> None:
    pid, _ = await make_provider(client, "cheat", cpu_cores=8, memory_mb=16000)
    puid = uuid.UUID(pid)
    await deposit_stake(session, puid, Decimal(settings.min_provider_stake))
    canary = await create_canary_job(session)
    await session.commit()
    await assign_job(session, canary.id, settings)

    from app.models import Provider

    job = await session.get(Job, canary.id)
    provider = await session.get(Provider, puid)
    req = AgentResultRequest(result_ref="dead", exit_code=0, proof={"output_sha256": "wrong"})
    await record_result(session, job, provider, req, settings)
    await session.commit()

    dispute = await session.scalar(select(Dispute).where(Dispute.provider_id == puid))
    assert dispute is not None and dispute.state is DisputeState.open
    # Stake is held in the disputed account, not yet burned.
    assert await account_balance(session, LedgerAccount.disputed, puid) > 0
    assert dispute.evidence["expected_output_hash"] is not None
