"""Session 10.7 — evidence is deterministic and serializable to a verifiable commitment."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job
from app.canary import create_canary_job
from app.disputes import open_dispute
from app.fraud_proof import canonical_evidence, evidence_commitment
from app.ledger import deposit_stake
from app.models import Dispute, Job, Provider
from app.results import record_result
from app.schemas import AgentResultRequest
from conftest import make_provider
from sqlalchemy import select

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


# ── canonical + commitment unit ─────────────────────────────────────────────────
def test_canonical_serialization_is_deterministic() -> None:
    a = {"b": 2, "a": 1, "nested": {"y": 2, "x": 1}}
    b = {"nested": {"x": 1, "y": 2}, "a": 1, "b": 2}  # same content, different order
    assert canonical_evidence(a) == canonical_evidence(b)
    assert evidence_commitment(a) == evidence_commitment(b)
    # Any change flips the commitment.
    assert evidence_commitment(a) != evidence_commitment({**a, "a": 2})


# ── stored commitment matches recomputation ─────────────────────────────────────
async def test_dispute_evidence_hash_is_verifiable(client, session, settings) -> None:
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
        AgentResultRequest(
            result_ref="x", exit_code=0, proof={"output_sha256": "wrong", "exit_code": 0}
        ),
        settings,
    )
    await session.commit()

    dispute = await session.scalar(select(Dispute).where(Dispute.provider_id == puid))
    # The stored commitment matches an independent recomputation over the evidence.
    assert dispute.evidence_hash == evidence_commitment(dispute.evidence)
    assert len(dispute.evidence_hash) == 64


async def test_open_dispute_sets_commitment(session, settings) -> None:
    dispute = await open_dispute(
        session,
        uuid.uuid4(),
        Decimal(0),
        reason="x",
        settings=settings,
        evidence={"k": "v", "n": 1},
    )
    assert dispute.evidence_hash == evidence_commitment({"k": "v", "n": 1})
