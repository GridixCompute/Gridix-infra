"""Session 7.2 — relay server: connection registry, DB auth, and WS tunnel lifecycle."""

import uuid

import pytest
from app.relay import ConnectionRegistry, create_relay_app, registry, resolve_provider
from conftest import register
from httpx import AsyncClient
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
    registry._conns.clear()


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
