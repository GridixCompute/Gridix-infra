"""Session 10.6 — graduated penalties: escalate repeat offenders, spare honest flakes."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.adjudicate import auto_adjudicate
from app.assignment import assign_job
from app.canary import create_canary_job
from app.ledger import deposit_stake
from app.models import Dispute, DisputeState, Job, Provider
from app.penalties import count_prior_offenses, graduated_slash
from app.results import record_result
from app.schemas import AgentResultRequest
from conftest import make_provider
from sqlalchemy import select

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


# ── curve unit ──────────────────────────────────────────────────────────────────
def test_graduated_slash_escalates_and_caps() -> None:
    base = Decimal(50)
    assert graduated_slash(base, 0) == Decimal(50)  # first offense
    assert graduated_slash(base, 1) == Decimal(100)  # repeat
    assert graduated_slash(base, 2) == Decimal(200)
    assert graduated_slash(base, 10) == Decimal(50) * 8  # capped


# ── escalation across offenses ──────────────────────────────────────────────────
async def _canary_fail(client, session, settings, provider_id) -> Dispute:
    canary = await create_canary_job(session)
    await session.commit()
    await assign_job(session, canary.id, settings)
    job = await session.get(Job, canary.id)
    provider = await session.get(Provider, provider_id)
    await record_result(
        session,
        job,
        provider,
        AgentResultRequest(
            result_ref="x", exit_code=0, proof={"output_sha256": "wrong", "exit_code": 0}
        ),
        settings,
    )
    await session.commit()
    return await session.scalar(
        select(Dispute)
        .where(Dispute.provider_id == provider_id, Dispute.state == DisputeState.open)
        .order_by(Dispute.created_at.desc())
    )


async def test_repeat_offender_is_slashed_harder(client, session, settings) -> None:
    pid, _ = await make_provider(client, "cheat", cpu_cores=8, memory_mb=16000)
    puid = uuid.UUID(pid)
    await deposit_stake(session, puid, Decimal(1000))

    first = await _canary_fail(client, session, settings, puid)
    assert Decimal(str(first.amount)) == Decimal(settings.slash_amount)  # first offense = base
    # Uphold it so it counts as a prior offense.
    await auto_adjudicate(session, first, settings)
    await session.commit()
    assert await count_prior_offenses(session, puid) == 1

    second = await _canary_fail(client, session, settings, puid)
    assert Decimal(str(second.amount)) == Decimal(settings.slash_amount) * 2  # escalated
