"""Redundant execution (K>1) end-to-end through the *HTTP agent path*.

This is the test the suite was missing: every existing quorum test drives
``assign_providers`` + ``record_result`` directly, so none of them exercised
``/agent/poll`` — and the poll/ownership path only ever served the single
``assigned_provider_id``, silently degrading K>1 to "trust one provider". These tests
prove each of the K providers is actually surfaced its work over HTTP and that quorum
finalizes only once all votes are in.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_providers, reap_expired_attempts
from app.ledger import deposit_stake
from app.matcher import CapabilityMatcher, ReputationMatcher, set_matcher
from app.models import Dispute, Job, JobAttempt, JobStatus, Provider
from conftest import auth, make_provider, register
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


async def _result_body(vote: str) -> dict:
    """A well-formed result whose proof hash matches its (content-addressed) ref."""
    return {"result_ref": vote, "exit_code": 0, "proof": {"output_sha256": vote, "exit_code": 0}}


async def test_all_k_providers_are_polled_and_quorum_settles(client, session, settings) -> None:
    """K=3: all three providers receive the job via /agent/poll, two agree, one dissents →
    the majority result is settled and the dissenter is slashed. The job finalizes only
    after the third vote, never after the first."""
    keys: dict[str, str] = {}
    for name in ("a", "b", "c"):
        pid, key = await make_provider(client, name, cpu_cores=8, memory_mb=16000)
        keys[pid] = key

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

    # Stake + reputation so the ReputationMatcher (stake-gated, high-rep for high-value)
    # considers all three, then assign — this is what the production scheduler does.
    for pid in keys:
        await deposit_stake(session, uuid.UUID(pid), Decimal(settings.min_provider_stake))
        p = await session.get(Provider, uuid.UUID(pid))
        p.reputation = 85.0
    await session.commit()
    providers = await assign_providers(session, job_id, settings)
    assert len(providers) == 3, "high-value K=3 job must be assigned to three providers"

    # THE REGRESSION ASSERTION: every assigned provider — not just the primary — is served
    # the job when it polls. Under the old single-`assigned_provider_id` path, two of these
    # three came back empty.
    for provider in providers:
        key = keys[str(provider.id)]
        polled = await client.post("/agent/poll", headers=auth(key))
        got = polled.json()["job"]
        assert got and got["id"] == str(job_id), f"provider {provider.id} was not polled the job"

    # Two vote AAA, one dissents with BBB. Finalization must wait for the third vote.
    votes = {str(providers[0].id): "AAA", str(providers[1].id): "AAA", str(providers[2].id): "BBB"}
    dissenter = providers[2]
    statuses = []
    for provider in providers:
        key = keys[str(provider.id)]
        await client.post(
            f"/agent/jobs/{job_id}/status", headers=auth(key), json={"status": "running"}
        )
        res = await client.post(
            f"/agent/jobs/{job_id}/result",
            headers=auth(key),
            json=await _result_body(votes[str(provider.id)]),
        )
        statuses.append(res.json()["status"])

    assert statuses[0] == JobStatus.running, "job must not finalize on the first vote"
    assert statuses[1] == JobStatus.running, "job must not finalize before quorum"
    assert statuses[2] == JobStatus.completed, "job finalizes once the Kth vote is in"

    job = await session.get(Job, job_id)
    await session.refresh(job)
    assert job.status is JobStatus.completed
    assert job.result_ref == "AAA", "the majority output wins"

    dispute = await session.scalar(select(Dispute).where(Dispute.provider_id == dissenter.id))
    assert dispute is not None, "the dissenter must be slashed (via a held dispute)"


async def test_secondary_provider_can_heartbeat_and_report(client, session, settings) -> None:
    """A non-primary redundant provider can hold its lease and report running over HTTP —
    the whole agent surface (not just poll) is keyed on the attempt, not the job's primary."""
    keys: dict[str, str] = {}
    for name in ("a", "b"):
        pid, key = await make_provider(client, name, cpu_cores=8, memory_mb=16000)
        keys[pid] = key

    _dev, dev_key = await register(client, "developer", "acme")
    r = await client.post(
        "/jobs",
        headers=auth(dev_key),
        json={"image_ref": "img", "is_high_value": True, "redundancy": 2},
    )
    job_id = uuid.UUID(r.json()["id"])

    for pid in keys:
        await deposit_stake(session, uuid.UUID(pid), Decimal(settings.min_provider_stake))
        p = await session.get(Provider, uuid.UUID(pid))
        p.reputation = 85.0
    await session.commit()
    providers = await assign_providers(session, job_id, settings)
    secondary = providers[1]  # NOT the job's assigned_provider_id
    key = keys[str(secondary.id)]

    job = await session.get(Job, job_id)
    assert job.assigned_provider_id != secondary.id, "guard: this is the non-primary provider"

    hb = await client.post("/agent/heartbeat", headers=auth(key), json={"job_id": str(job_id)})
    assert hb.status_code == 200, hb.text
    st = await client.post(
        f"/agent/jobs/{job_id}/status", headers=auth(key), json={"status": "running"}
    )
    assert st.status_code == 200, st.text


async def _setup_kn_job(client, session, settings, names, redundancy):
    """Register providers (staked + reputable), submit a high-value job, and assign it."""
    keys: dict[str, str] = {}
    for name in names:
        pid, key = await make_provider(client, name, cpu_cores=8, memory_mb=16000)
        keys[pid] = key
    _dev, dev_key = await register(client, "developer", "acme")
    r = await client.post(
        "/jobs",
        headers=auth(dev_key),
        json={
            "image_ref": "img",
            "is_high_value": True,
            "redundancy": redundancy,
            "resource_spec": {"cpu_cores": 1, "memory_mb": 1000},
        },
    )
    job_id = uuid.UUID(r.json()["id"])
    for pid in keys:
        await deposit_stake(session, uuid.UUID(pid), Decimal(settings.min_provider_stake))
        p = await session.get(Provider, uuid.UUID(pid))
        p.reputation = 85.0
    await session.commit()
    providers = await assign_providers(session, job_id, settings)
    return keys, job_id, providers


async def _expire_attempt(session, job_id, provider_id) -> None:
    attempt = await session.scalar(
        select(JobAttempt).where(JobAttempt.job_id == job_id, JobAttempt.provider_id == provider_id)
    )
    attempt.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)


async def test_kn_survives_one_provider_dying(client, session, settings) -> None:
    """K=3 with one provider that never returns: the attempt reaper marks it a non-vote and
    the job settles on the surviving two-of-three majority — no hang, majority paid."""
    keys, job_id, providers = await _setup_kn_job(client, session, settings, ("a", "b", "c"), 3)

    for provider in providers[:2]:  # two agree; the third goes silent
        await client.post(
            f"/agent/jobs/{job_id}/result",
            headers=auth(keys[str(provider.id)]),
            json=await _result_body("AAA"),
        )
    job = await session.get(Job, job_id)
    await session.refresh(job)
    assert job.status is JobStatus.running, "must not finalize while the third vote may arrive"

    await _expire_attempt(session, job_id, providers[2].id)
    await session.commit()
    await reap_expired_attempts(session, settings)

    job = await session.get(Job, job_id)
    await session.refresh(job)
    assert job.status is JobStatus.completed, "the surviving majority settles the job"
    assert job.result_ref == "AAA"
    assert float(job.cost_final) > 0, "the majority is paid"


async def test_kn_fails_and_refunds_when_no_majority_survives(client, session, settings) -> None:
    """K=3 where only one provider returns and the other two die: no majority is possible, so
    the job fails and the developer is fully refunded (cost_final 0)."""
    keys, job_id, providers = await _setup_kn_job(client, session, settings, ("a", "b", "c"), 3)

    await client.post(
        f"/agent/jobs/{job_id}/result",
        headers=auth(keys[str(providers[0].id)]),
        json=await _result_body("AAA"),
    )
    for dead in providers[1:]:
        await _expire_attempt(session, job_id, dead.id)
    await session.commit()
    await reap_expired_attempts(session, settings)

    job = await session.get(Job, job_id)
    await session.refresh(job)
    assert job.status is JobStatus.failed, "one vote cannot reach a 3-way quorum"
    assert float(job.cost_final) == 0.0, "the developer is fully refunded"
