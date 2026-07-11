"""Session 7.7 — bandwidth accounting: record, aggregate, and meter transfer points."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job
from app.bandwidth import provider_bandwidth, record_bandwidth
from app.models import BandwidthDirection
from conftest import auth, make_provider, register
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


# ── record + aggregate ──────────────────────────────────────────────────────────
async def test_record_and_aggregate(client: AsyncClient, session) -> None:
    pid, _ = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    puid = uuid.UUID(pid)
    await record_bandwidth(session, puid, BandwidthDirection.ingress, 1000)
    await record_bandwidth(session, puid, BandwidthDirection.egress, 500)
    await record_bandwidth(session, puid, BandwidthDirection.ingress, 200)
    await record_bandwidth(session, puid, BandwidthDirection.ingress, 0)  # ignored
    await session.commit()

    bw = await provider_bandwidth(session, puid)
    assert bw == {"ingress": 1200, "egress": 500, "total": 1700}

    # `since` windows the aggregate.
    assert (await provider_bandwidth(session, puid, since=datetime(2000, 1, 1, tzinfo=UTC)))[
        "total"
    ] == 1700
    future = datetime.now(UTC) + timedelta(hours=1)
    assert (await provider_bandwidth(session, puid, since=future))["total"] == 0


# ── metering at the transfer points ─────────────────────────────────────────────
async def test_input_download_records_ingress(client: AsyncClient, session, settings) -> None:
    pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    _dev, dev_key = await register(client, "developer", "acme")
    payload = b"x" * 1234
    ref = (
        await client.post(
            "/blobs",
            headers=auth(dev_key),
            files={"file": ("in", payload, "application/octet-stream")},
        )
    ).json()["ref"]
    r = await client.post(
        "/jobs", headers=auth(dev_key), json={"image_ref": "img", "input_ref": ref}
    )
    job_id = uuid.UUID(r.json()["id"])
    await assign_job(session, job_id, settings)

    dl = await client.get(f"/agent/jobs/{job_id}/input", headers=auth(prov_key))
    assert dl.content == payload

    bw = (await client.get("/providers/me/bandwidth", headers=auth(prov_key))).json()
    assert bw["ingress_bytes"] == 1234
    assert bw["egress_bytes"] == 0


async def test_result_upload_records_egress(client: AsyncClient) -> None:
    _pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    output = b"result" * 100  # 600 bytes
    up = await client.post(
        "/agent/blobs",
        headers=auth(prov_key),
        files={"file": ("result", output, "application/octet-stream")},
    )
    assert up.status_code == 201

    bw = (await client.get("/providers/me/bandwidth", headers=auth(prov_key))).json()
    assert bw["egress_bytes"] == 600
    assert bw["total_bytes"] == 600
