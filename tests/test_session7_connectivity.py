"""Session 7.1 — control channel: long-poll, presence, connect/silence detection."""

import time
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job
from app.models import Provider
from app.presence import is_connected, mark_seen
from conftest import auth, make_provider, register
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


# ── presence unit ───────────────────────────────────────────────────────────────
def test_mark_seen_opens_connection_window_and_detects_silence() -> None:
    p = Provider(name="p")
    now = datetime.now(UTC)
    assert not is_connected(p, now, 30)  # never seen

    mark_seen(p, now, 30)
    first_connected = p.connected_at
    assert first_connected == now
    assert is_connected(p, now, 30)

    # A later call within the window keeps the same connection window open.
    mark_seen(p, now + timedelta(seconds=10), 30)
    assert p.connected_at == first_connected

    # Gone silent past the timeout.
    assert not is_connected(p, now + timedelta(seconds=40), 30)

    # A call after silence opens a NEW window.
    reconnect = now + timedelta(seconds=50)
    mark_seen(p, reconnect, 30)
    assert p.connected_at == reconnect


# ── long-poll ───────────────────────────────────────────────────────────────────
async def test_poll_returns_immediately_when_job_assigned(
    client: AsyncClient, session, settings
) -> None:
    pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    _dev, dev_key = await register(client, "developer", "Acme")
    r = await client.post("/jobs", headers=auth(dev_key), json={"image_ref": "img"})
    job_id = uuid.UUID(r.json()["id"])
    await assign_job(session, job_id, settings)

    start = time.monotonic()
    resp = await client.post("/agent/poll", headers=auth(prov_key))
    elapsed = time.monotonic() - start
    assert resp.json()["job"]["id"] == str(job_id)
    assert elapsed < settings.poll_hold_seconds  # did not hold


async def test_poll_holds_then_returns_empty(client: AsyncClient, settings) -> None:
    _pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    start = time.monotonic()
    resp = await client.post("/agent/poll", headers=auth(prov_key))
    elapsed = time.monotonic() - start
    assert resp.json()["job"] is None
    # Held roughly for the configured hold before giving up.
    assert elapsed >= settings.poll_hold_seconds * 0.5


# ── keepalive / presence via API ────────────────────────────────────────────────
async def test_ping_marks_provider_connected(client: AsyncClient) -> None:
    _pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    resp = await client.post("/agent/ping", headers=auth(prov_key))
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True
    assert body["last_seen"] is not None
    assert body["connected_at"] is not None

    me = await client.get("/providers/me", headers=auth(prov_key))
    assert me.json()["last_seen"] is not None


async def test_poll_refreshes_presence(client: AsyncClient) -> None:
    _pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    # An empty poll (which holds briefly) still records presence up front.
    await client.post("/agent/poll", headers=auth(prov_key))
    me = await client.get("/providers/me", headers=auth(prov_key))
    assert me.json()["last_seen"] is not None
