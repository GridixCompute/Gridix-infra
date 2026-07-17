"""The relay tunnel must refresh presence on ping, not only at auth.

dispatch selects nodes by the DB ``last_seen`` window (``presence.is_connected``), not by the
relay's in-memory tunnel registry, and only auth ever stamped ``last_seen``. So a node whose
tunnel stayed open but idle aged out of selection ``connection_timeout_seconds`` after
connecting — the coordinator answered 503 "no node serving" for a node that was right there on
the wire. The fix re-stamps presence on each keepalive ping; the agent pings well inside the
window.

Two halves, pinned separately because the honest integration (drive the WebSocket *and* let the
refresh hit the database) deadlocks under Starlette's TestClient — the same aiosqlite teardown
hang that already forces the registry writes to be stubbed in test_session7_relay.py:
  - the relay calls the presence refresh on ping (wiring), and
  - that refresh returns a stale-but-connected node to ``select_node`` (effect).
"""

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from app.config import get_settings
from app.dispatch import NoNodeAvailableError, select_node
from app.presence import mark_seen
from app.relay import create_relay_app
from starlette.testclient import TestClient
from test_dispatch import MODEL, NOW, make_node


def _relay(pid: uuid.UUID) -> TestClient:
    async def _auth(token: str) -> uuid.UUID | None:
        return pid if token == "good-key" else None

    return TestClient(create_relay_app(authenticate=_auth))


def test_relay_refreshes_presence_on_ping() -> None:
    """Wiring: a keepalive ping re-stamps presence, beyond the single stamp at auth.

    The registry writes are stubbed because a real one deadlocks TestClient's portal on
    teardown; the stub also lets us count that the refresh fires on ping. Remove the refresh in
    relay.py and ``mark_provider_seen`` is called only once (at auth) — this goes red.
    """
    pid = uuid.uuid4()
    with (
        patch("app.relay.record_models", new=AsyncMock()),
        patch("app.relay.mark_provider_seen", new=AsyncMock()) as seen,
        patch("app.relay.clear_models", new=AsyncMock()),
    ):
        tc = _relay(pid)
        with tc.websocket_connect("/relay/agent") as ws:
            ws.send_json({"type": "auth", "key": "good-key"})
            assert ws.receive_json()["type"] == "auth_ok"
            stamped_at_auth = seen.call_count  # 1: stamped once, at auth
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            assert seen.call_count > stamped_at_auth  # the ping stamped it again
    seen.assert_awaited_with(pid)


async def test_presence_refresh_returns_a_stale_node_to_selection(session) -> None:
    """Effect: the refresh the relay runs on ping puts an aged-out node back in selection.

    A node last seen outside the connection window is not dispatchable (dispatch reads presence,
    not the live tunnel); re-stamping it — exactly what ``mark_provider_seen`` does on ping —
    makes ``select_node`` choose it again.
    """
    settings = get_settings()
    stale = NOW - timedelta(seconds=settings.connection_timeout_seconds + 60)
    provider = await make_node(session, last_seen=stale)

    with pytest.raises(NoNodeAvailableError):
        await select_node(session, model=MODEL, now=NOW, settings=settings)

    mark_seen(provider, NOW, settings.connection_timeout_seconds)
    await session.commit()

    assert await select_node(session, model=MODEL, now=NOW, settings=settings) == provider.id
