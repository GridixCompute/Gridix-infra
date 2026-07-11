"""Session 9.6 — runtime secrets: short-lived, job-scoped, never persisted/logged."""

import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job
from app.config import get_settings
from app.models import Job, JobStatus
from app.secrets_broker import SecretReleaseError, mint_job_secrets
from conftest import auth, make_provider, register

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


# ── minting unit ────────────────────────────────────────────────────────────────
def test_mint_is_job_scoped_and_expiring() -> None:
    s = get_settings()
    j1 = Job(id=uuid.uuid4(), image_ref="i", status=JobStatus.running, resource_spec={})
    j2 = Job(id=uuid.uuid4(), image_ref="i", status=JobStatus.running, resource_spec={})
    now = 1_000_000
    s1, exp1 = mint_job_secrets(j1, s, now=now)
    s2, _ = mint_job_secrets(j2, s, now=now)
    # Tokens are scoped to the job (different jobs → different tokens) and time-bounded.
    assert s1["GRIDIX_JOB_TOKEN"] != s2["GRIDIX_JOB_TOKEN"]
    assert exp1 > now


def test_mint_refuses_when_not_in_flight() -> None:
    job = Job(id=uuid.uuid4(), image_ref="i", status=JobStatus.completed, resource_spec={})
    with pytest.raises(SecretReleaseError):
        mint_job_secrets(job, get_settings())


# ── endpoint + non-persistence ──────────────────────────────────────────────────
async def _assigned(client, session, settings):
    _pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    _dev, dev_key = await register(client, "developer", "acme")
    r = await client.post("/jobs", headers=auth(dev_key), json={"image_ref": "img"})
    job_id = uuid.UUID(r.json()["id"])
    await assign_job(session, job_id, settings)
    return job_id, prov_key, dev_key


async def test_assigned_agent_gets_secrets_not_persisted(client, session, settings) -> None:
    job_id, prov_key, dev_key = await _assigned(client, session, settings)
    resp = await client.get(f"/agent/jobs/{job_id}/secrets", headers=auth(prov_key))
    assert resp.status_code == 200
    body = resp.json()
    token = body["secrets"]["GRIDIX_JOB_TOKEN"]
    assert body["expires_at"] > time.time()

    # The secret value is nowhere in the job's persisted audit trail.
    audit = (await client.get(f"/jobs/{job_id}/audit", headers=auth(dev_key))).json()
    assert token not in str(audit)


async def test_secrets_unavailable_after_job_ends(client, session, settings) -> None:
    job_id, prov_key, _dev_key = await _assigned(client, session, settings)
    job = await session.get(Job, job_id)
    job.status = JobStatus.completed
    await session.commit()
    resp = await client.get(f"/agent/jobs/{job_id}/secrets", headers=auth(prov_key))
    assert resp.status_code == 409
