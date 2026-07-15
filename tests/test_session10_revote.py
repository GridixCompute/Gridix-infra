"""Session 10.5 — quorum re-vote resolves redundant-execution disputes by majority."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.adjudicate import quorum_revote
from app.assignment import assign_providers
from app.disputes import open_dispute
from app.ledger import deposit_stake
from app.matcher import CapabilityMatcher, ReputationMatcher, set_matcher
from app.models import Dispute, DisputeState, Job, Provider
from app.results import record_result
from app.schemas import AgentResultRequest
from conftest import HASH_A, HASH_B, auth, make_provider, register
from sqlalchemy import select

pytestmark = pytest.mark.usefixtures("_no_redis", "_rep_matcher")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


@pytest.fixture
def _rep_matcher():
    set_matcher(ReputationMatcher())
    yield
    set_matcher(CapabilityMatcher())


async def test_revote_upholds_dissenter(client, session, settings) -> None:
    """3 providers: two agree, one dissents → the dissenter's dispute is upheld by revote."""
    ids = []
    for name in ("a", "b", "c"):
        pid, _ = await make_provider(client, name, cpu_cores=8, memory_mb=16000)
        ids.append(pid)
    _dev, dev_key = await register(client, "developer", "acme")
    r = await client.post(
        "/jobs",
        headers=auth(dev_key),
        json={
            "image_ref": "img",
            "is_high_value": True,
            "redundancy": 3,
            "resource_spec": {"cpu_cores": 1, "memory_mb": 1000},
        },
    )
    job_id = uuid.UUID(r.json()["id"])

    # Session writes only after all HTTP writes (avoid interleaving SQLite connections).
    for pid in ids:
        await deposit_stake(session, uuid.UUID(pid), Decimal(settings.min_provider_stake))
        p = await session.get(Provider, uuid.UUID(pid))
        p.reputation = 85.0
    await session.commit()

    providers = await assign_providers(session, job_id, settings)
    job = await session.get(Job, job_id)
    votes = {
        str(providers[0].id): HASH_A,
        str(providers[1].id): HASH_A,
        str(providers[2].id): HASH_B,
    }
    dissenter = providers[2]
    for provider in providers:
        p = await session.get(Provider, provider.id)
        await record_result(
            session,
            job,
            p,
            AgentResultRequest(
                result_ref=votes[str(provider.id)],
                exit_code=0,
                proof={"output_sha256": votes[str(provider.id)], "exit_code": 0},
            ),
            settings,
        )
    await session.commit()

    dispute = await session.scalar(select(Dispute).where(Dispute.provider_id == dissenter.id))
    assert dispute is not None
    outcome = await quorum_revote(session, dispute, settings)
    assert outcome is DisputeState.upheld  # dissenter disagreed with the AAA majority


async def test_revote_overturns_when_matches_majority(client, session, settings) -> None:
    """If the disputed provider actually matched the majority, the slash is overturned."""
    set_matcher(CapabilityMatcher())
    pid, _ = await make_provider(client, "p", cpu_cores=8, memory_mb=16000)
    puid = uuid.UUID(pid)
    _dev, dev_key = await register(client, "developer", "acme")
    r = await client.post("/jobs", headers=auth(dev_key), json={"image_ref": "img"})
    job_id = uuid.UUID(r.json()["id"])

    await deposit_stake(session, puid, Decimal(100))
    await session.commit()

    providers = await assign_providers(session, job_id, settings)
    job = await session.get(Job, job_id)
    p = await session.get(Provider, providers[0].id)  # this is provider "p"
    await record_result(
        session,
        job,
        p,
        AgentResultRequest(
            result_ref=HASH_A, exit_code=0, proof={"output_sha256": HASH_A, "exit_code": 0}
        ),
        settings,
    )
    # A mistaken dispute opened against the provider that ran (and matched the majority).
    dispute = await open_dispute(
        session, puid, Decimal(50), reason="quorum", settings=settings, job_id=job_id
    )
    await session.commit()

    outcome = await quorum_revote(session, dispute, settings)
    assert outcome is DisputeState.overturned  # provider's AAA == majority AAA
