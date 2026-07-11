"""Session 7.2-7.3 — relay: registry, DB auth, WS tunnel lifecycle, and request routing."""

import asyncio
import uuid

import pytest
from app.config import get_settings
from app.relay import (
    ConnectionRegistry,
    Tunnel,
    TunnelClosedError,
    create_relay_app,
    registry,
    resolve_provider,
)
from conftest import register
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient


# ── ConnectionRegistry unit ─────────────────────────────────────────────────────
async def test_registry_register_lookup_supersede_unregister() -> None:
    reg = ConnectionRegistry()
    pid = uuid.uuid4()
    conn_a, conn_b = object(), object()

    assert await reg.register(pid, conn_a) is None
    assert await reg.get(pid) is conn_a
    assert await reg.count() == 1
    assert await reg.is_connected(pid)

    # Re-registering returns the superseded connection.
    assert await reg.register(pid, conn_b) is conn_a
    assert await reg.get(pid) is conn_b

    # Unregister only removes if it's still the current connection.
    await reg.unregister(pid, conn_a)  # stale — no-op
    assert await reg.get(pid) is conn_b
    await reg.unregister(pid, conn_b)
    assert await reg.get(pid) is None
    assert not await reg.is_connected(pid)


# ── DB-backed authentication ────────────────────────────────────────────────────
async def test_resolve_provider_validates_keys(client: AsyncClient) -> None:
    pid, prov_key = await register(client, "provider", "farm")
    _did, dev_key = await register(client, "developer", "acme")

    assert str(await resolve_provider(prov_key)) == pid
    assert await resolve_provider(dev_key) is None  # developer key rejected
    assert await resolve_provider("grdx_bogus") is None


# ── WebSocket tunnel lifecycle (server side, injected auth) ──────────────────────
@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    registry._tunnels.clear()


def _relay_with_fake_auth(provider_id: uuid.UUID) -> TestClient:
    async def _auth(token: str) -> uuid.UUID | None:
        return provider_id if token == "good-key" else None

    return TestClient(create_relay_app(authenticate=_auth))


def test_tunnel_registers_and_is_lookupable() -> None:
    """An authed agent holds a tunnel; the relay can look up its live connection."""
    pid = uuid.uuid4()
    tc = _relay_with_fake_auth(pid)
    assert tc.get("/relay/health").json()["tunnels"] == 0

    with tc.websocket_connect("/relay/agent") as ws:
        ws.send_json({"type": "auth", "key": "good-key"})
        assert ws.receive_json() == {"type": "auth_ok", "provider_id": str(pid)}
        # The provider is now routable through the relay.
        assert tc.get("/relay/health").json()["tunnels"] == 1
        # Keepalive round-trips.
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_tunnel_rejects_bad_key() -> None:
    tc = _relay_with_fake_auth(uuid.uuid4())
    with tc.websocket_connect("/relay/agent") as ws:
        ws.send_json({"type": "auth", "key": "wrong"})
        assert ws.receive_json()["type"] == "auth_error"
    assert tc.get("/relay/health").json()["tunnels"] == 0


# ── Tunnel request/response correlation (7.3) ────────────────────────────────────
class _FakeWS:
    """Records frames the tunnel sends; used to drive Tunnel unit tests."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, obj: dict) -> None:
        self.sent.append(obj)

    async def close(self, code: int = 1000) -> None:
        pass


async def _await_first_frame(ws: _FakeWS) -> dict:
    for _ in range(200):
        if ws.sent:
            return ws.sent[-1]
        await asyncio.sleep(0.005)
    raise AssertionError("no frame sent")


async def test_tunnel_call_correlates_response() -> None:
    ws = _FakeWS()
    tunnel = Tunnel(ws)

    async def respond() -> None:
        req = await _await_first_frame(ws)
        assert req["type"] == "request" and req["job_id"] == "j1"
        await tunnel.handle_incoming(
            {
                "type": "response",
                "request_id": req["request_id"],
                "status": 200,
                "payload": {"ok": True},
            }
        )

    task = asyncio.create_task(respond())
    resp = await tunnel.call(job_id="j1", method="GET", payload={"a": 1}, timeout=2)
    await task
    assert resp["status"] == 200 and resp["payload"] == {"ok": True}


async def test_tunnel_call_times_out() -> None:
    tunnel = Tunnel(_FakeWS())
    with pytest.raises(asyncio.TimeoutError):
        await tunnel.call(job_id=None, method="GET", payload={}, timeout=0.1)


async def test_tunnel_drop_fails_pending_calls() -> None:
    ws = _FakeWS()
    tunnel = Tunnel(ws)

    async def drop() -> None:
        await _await_first_frame(ws)
        tunnel.fail_all(TunnelClosedError("gone"))

    task = asyncio.create_task(drop())
    with pytest.raises(TunnelClosedError):
        await tunnel.call(job_id=None, method="GET", payload={}, timeout=2)
    await task


# ── End-to-end: coordinator → relay → NAT'd provider → relay → coordinator ───────
def _relay_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_relay_app()), base_url="http://relay")


async def test_coordinator_reaches_provider_through_tunnel() -> None:
    """A coordinator HTTP call is bridged onto a registered provider tunnel and the
    provider's reply is returned — proving the full round trip through the relay."""
    pid = uuid.uuid4()
    fake_ws = _FakeWS()
    tunnel = Tunnel(fake_ws)
    await registry.register(pid, tunnel)
    secret = get_settings().secret_key

    async with _relay_client() as ac:
        post = asyncio.create_task(
            ac.post(
                f"/relay/providers/{pid}/request",
                headers={"Authorization": f"Bearer {secret}"},
                json={"job_id": "job-1", "method": "POST", "payload": {"x": 1}},
            )
        )
        # The provider receives the bridged request and replies over the tunnel.
        req = await _await_first_frame(fake_ws)
        assert req["type"] == "request" and req["job_id"] == "job-1"
        await tunnel.handle_incoming(
            {
                "type": "response",
                "request_id": req["request_id"],
                "status": 200,
                "payload": {"pong": req["payload"]},
            }
        )
        resp = await post

    assert resp.status_code == 200
    assert resp.json() == {"status": 200, "payload": {"pong": {"x": 1}}}


async def test_request_to_disconnected_provider_is_503() -> None:
    secret = get_settings().secret_key
    async with _relay_client() as ac:
        resp = await ac.post(
            f"/relay/providers/{uuid.uuid4()}/request",
            headers={"Authorization": f"Bearer {secret}"},
            json={"method": "GET", "payload": {}},
        )
    assert resp.status_code == 503


async def test_request_requires_internal_secret() -> None:
    async with _relay_client() as ac:
        resp = await ac.post(
            f"/relay/providers/{uuid.uuid4()}/request",
            headers={"Authorization": "Bearer wrong"},
            json={"method": "GET", "payload": {}},
        )
    assert resp.status_code == 401
