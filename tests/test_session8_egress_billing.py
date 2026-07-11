"""Session 8.6 — egress accounting feeds a data-cost line item into settlement."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job
from app.pricing import data_cost
from app.storage import content_digest
from conftest import auth, make_provider, register
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


async def test_data_heavy_job_gets_data_cost_line(client: AsyncClient, session, settings) -> None:
    """A job that moved data shows a data_cost ledger entry at settlement."""
    _pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    _dev, dev_key = await register(client, "developer", "acme")

    payload = b"m" * 1_000_000  # 1 MB model input
    ref = (
        await client.post(
            "/blobs",
            headers=auth(dev_key),
            files={"file": ("model", payload, "application/octet-stream")},
        )
    ).json()["ref"]
    r = await client.post(
        "/jobs", headers=auth(dev_key), json={"image_ref": "img", "input_ref": ref}
    )
    job_id = uuid.UUID(r.json()["id"])
    await assign_job(session, job_id, settings)

    # The download meters ingress against the job (Session 7.7).
    await client.get(f"/agent/jobs/{job_id}/input", headers=auth(prov_key))
    await client.post(
        f"/agent/jobs/{job_id}/status", headers=auth(prov_key), json={"status": "running"}
    )
    output = b"the result"
    up = await client.post(
        "/agent/blobs",
        headers=auth(prov_key),
        files={"file": ("result", output, "application/octet-stream")},
    )
    await client.post(
        f"/agent/jobs/{job_id}/result",
        headers=auth(prov_key),
        json={
            "result_ref": up.json()["ref"],
            "exit_code": 0,
            "proof": {"output_sha256": content_digest(output), "exit_code": 0},
            "timed_out": False,
        },
    )

    audit = (await client.get(f"/jobs/{job_id}/audit", headers=auth(dev_key))).json()
    data_rows = [row for row in audit["ledger"] if row["reason"] == "data_cost"]
    assert len(data_rows) == 2  # balanced: developer debit + protocol credit
    expected = float(data_cost(1_000_000, settings))
    assert any(abs(float(row["amount"]) - expected) < 1e-9 for row in data_rows)
    assert expected > 0
