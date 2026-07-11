"""Session 10.2 — every slash links reproducible evidence, pullable by the provider."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job
from app.canary import CANARY_EXPECTED_HASH, create_canary_job
from app.ledger import deposit_stake
from app.models import Dispute, Job, Provider
from app.results import record_result
from app.schemas import AgentResultRequest
from conftest import auth, make_provider
from sqlalchemy import select

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


async def test_slash_evidence_is_complete_and_pullable(client, session, settings) -> None:
    pid, prov_key = await make_provider(client, "cheat", cpu_cores=8, memory_mb=16000)
    puid = uuid.UUID(pid)
    await deposit_stake(session, puid, Decimal(settings.min_provider_stake))
    canary = await create_canary_job(session)
    await session.commit()
    await assign_job(session, canary.id, settings)

    job = await session.get(Job, canary.id)
    provider = await session.get(Provider, puid)
    req = AgentResultRequest(result_ref="garbage", exit_code=0, proof={"output_sha256": "wrong"})
    await record_result(session, job, provider, req, settings)
    await session.commit()

    dispute = await session.scalar(select(Dispute).where(Dispute.provider_id == puid))
    ev = dispute.evidence
    # Reproducible: expected vs submitted, proof, and the input reference are all present.
    assert ev["expected_output_hash"] == CANARY_EXPECTED_HASH
    assert ev["submitted_output_hash"] == "wrong"
    assert ev["submitted_result_ref"] == "garbage"
    assert ev["proof"] == {"output_sha256": "wrong"}
    assert "quorum_votes" in ev

    # The provider can pull the full evidence set via the API.
    listed = await client.get("/disputes/me", headers=auth(prov_key))
    assert listed.status_code == 200 and len(listed.json()) == 1
    detail = await client.get(f"/disputes/{dispute.id}", headers=auth(prov_key))
    assert detail.json()["evidence"]["submitted_output_hash"] == "wrong"


async def test_provider_can_contest_open_dispute(client, session, settings) -> None:
    pid, prov_key = await make_provider(client, "cheat", cpu_cores=8, memory_mb=16000)
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
    resp = await client.post(f"/disputes/{dispute.id}/contest", headers=auth(prov_key))
    assert resp.status_code == 200 and resp.json()["state"] == "under_review"
