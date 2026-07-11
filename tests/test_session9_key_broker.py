"""Session 9.3 — key brokering: assigned agent only, job lifetime only."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job
from app.config import get_settings
from app.crypto import generate_data_key, wrap_key
from app.models import Job, JobStatus
from conftest import auth, make_provider, register
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


async def _submit_confidential(client: AsyncClient) -> tuple[uuid.UUID, str, str]:
    _dev, dev_key = await register(client, "developer", "acme")
    dek = generate_data_key()
    wrapped = wrap_key(dek, get_settings().kek).decode()
    r = await client.post(
        "/jobs",
        headers=auth(dev_key),
        json={"image_ref": "img", "data_tier": "encrypted_at_rest", "wrapped_key": wrapped},
    )
    return uuid.UUID(r.json()["id"]), dek, dev_key


async def test_assigned_agent_gets_the_key(client: AsyncClient, session, settings) -> None:
    _pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    job_id, dek, _dev_key = await _submit_confidential(client)
    await assign_job(session, job_id, settings)

    resp = await client.get(f"/agent/jobs/{job_id}/key", headers=auth(prov_key))
    assert resp.status_code == 200
    assert resp.json()["data_key"] == dek  # broker unwrapped the DEK correctly


async def test_other_provider_cannot_get_the_key(client: AsyncClient, session, settings) -> None:
    _pid, _prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    _other, other_key = await make_provider(client, "intruder", cpu_cores=8, memory_mb=16000)
    job_id, _dek, _dev_key = await _submit_confidential(client)
    await assign_job(session, job_id, settings)  # assigned to the first capable provider

    resp = await client.get(f"/agent/jobs/{job_id}/key", headers=auth(other_key))
    assert resp.status_code == 404


async def test_key_unavailable_after_job_ends(client: AsyncClient, session, settings) -> None:
    _pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    job_id, _dek, _dev_key = await _submit_confidential(client)
    await assign_job(session, job_id, settings)

    # Job reaches a terminal state → the key is no longer released.
    job = await session.get(Job, job_id)
    job.status = JobStatus.completed
    await session.commit()

    resp = await client.get(f"/agent/jobs/{job_id}/key", headers=auth(prov_key))
    assert resp.status_code == 409
