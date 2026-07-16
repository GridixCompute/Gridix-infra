"""The relay joins the startup contract, and stops holding sockets open for free.

Two findings, one root cause. app/relay.py is a fourth process, and the only one that
never ran init_secrets: the API, scheduler and chain worker all do it at startup, while
this one built its app at import time with no hook. So the wave-1 TLS and
secret-separation work — both real, both tested — simply never executed here.

The consequence was not theoretical. `relay_key` falls back to `secret_key`, whose default
is the constant published in this repository, so a relay deployed with only
GRIDIX_SECRET_KEY set authenticated its internal bridge on a value anyone can read. In the
dispatch model the relay carries every inference request, so that bridge is the money path.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.config import Settings, get_settings
from app.relay import (
    _AUTH_TIMEOUT_SECONDS,
    _MAX_CONNECTIONS,
    _idle_timeout,
    create_relay_app,
)
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture(autouse=True)
def _registry_writes():
    """The tunnel handler writes to the DB on connect; TestClient can't (see the relay tests)."""
    with (
        patch("app.relay.record_models", new=AsyncMock()),
        patch("app.relay.mark_provider_seen", new=AsyncMock()),
        patch("app.relay.clear_models", new=AsyncMock()),
    ):
        yield


def _relay(provider_id: uuid.UUID | None = None) -> TestClient:
    pid = provider_id or uuid.uuid4()

    async def _auth(token: str) -> uuid.UUID | None:
        return pid if token == "good-key" else None

    return TestClient(create_relay_app(authenticate=_auth))


def _prod(**over) -> Settings:
    """A prod Settings with everything valid unless a test breaks one thing."""
    base = {
        "env": "prod",
        "secret_key": "legacy-not-used",
        "hmac_key": "k1-distinct",
        "operator_secret": "k2-distinct",
        "relay_secret": "k3-distinct",
        "endpoint_key": "k4-distinct",
        "database_url": "postgresql+asyncpg://u:p@db/gridix?ssl=require",
        "redis_url": "rediss://cache:6379/0",
        "relay_internal_url": "https://relay.internal:8100",
        "public_base_url": "https://api.gridix.dev",
    }
    base.update(over)
    return Settings(**base)


class TestTheRelayValidatesItsConfigAtStartup:
    def test_starting_up_runs_init_secrets(self) -> None:
        """The claim: the relay now joins the contract the other three processes keep."""
        with patch("app.relay.init_secrets") as init, _relay():
            pass
        init.assert_called_once()

    def test_a_prod_relay_on_the_dev_default_secret_refuses_to_start(self) -> None:
        """The finding, as an exploit precondition: this is what shipped.

        With only GRIDIX_SECRET_KEY set, relay_key resolves to it, and its default is the
        constant in config.py. The relay used to start happily and authenticate its bridge
        on a published string; now it will not start at all.
        """
        from app.secret_manager import SecretConfigurationError, validate_secret_config

        with pytest.raises(SecretConfigurationError):
            validate_secret_config(Settings(env="prod"))

    def test_a_prod_relay_reusing_one_secret_for_everything_refuses_to_start(self) -> None:
        from app.secret_manager import SecretConfigurationError, validate_secret_config

        with pytest.raises(SecretConfigurationError, match="reuse"):
            validate_secret_config(_prod(relay_secret="k1-distinct"))

    def test_a_prod_relay_reached_over_cleartext_refuses_to_start(self) -> None:
        """TLS everywhere (wave 1) was enforced in three processes and not this one."""
        from app.net_security import TlsConfigurationError, validate_tls_config

        with pytest.raises(TlsConfigurationError):
            validate_tls_config(_prod(relay_internal_url="http://relay.internal:8100"))

    def test_a_correctly_configured_prod_relay_starts(self) -> None:
        """The other direction, or the tests above would pass on a relay that never starts."""
        from app.net_security import validate_tls_config
        from app.secret_manager import validate_secret_config

        validate_secret_config(_prod())
        validate_tls_config(_prod())

    def test_dev_still_starts_on_defaults(self) -> None:
        """Hardening prod must not make local development need a secret manager."""
        with _relay() as tc:
            assert tc.get("/relay/health").status_code == 200


class TestSocketsCannotBeHeldForFree:
    def test_a_socket_that_never_authenticates_is_dropped(self) -> None:
        """Connect, say nothing, hold. Pre-auth sockets are in no registry, so nothing
        counted them and nothing timed them out — N of them cost an attacker nothing.

        Asserts the close CODE, not merely that something was raised: a socket dropped for
        the wrong reason would satisfy a bare `raises(Exception)`, and this test would then
        pass with the deadline deleted.
        """
        tc = _relay()
        with (
            patch("app.relay._AUTH_TIMEOUT_SECONDS", 0.2),
            pytest.raises(WebSocketDisconnect) as caught,
            tc.websocket_connect("/relay/agent") as ws,
        ):
            # Never send an auth frame. The relay must close on us.
            ws.receive_json()
        assert caught.value.code == 1008

    def test_the_auth_deadline_is_finite_and_sane(self) -> None:
        assert 0 < _AUTH_TIMEOUT_SECONDS <= 60

    def test_an_authenticated_tunnel_still_has_an_idle_deadline(self) -> None:
        """A live tunnel that goes silent holds a slot exactly as well as a dead one."""
        assert _idle_timeout() >= 30
        # Tied to the keepalive cadence, so the two cannot drift apart.
        assert _idle_timeout() >= get_settings().agent_heartbeat_interval_seconds * 3

    def test_a_healthy_tunnel_is_not_dropped(self) -> None:
        """The other direction: the deadline must not evict a node that is talking."""
        tc = _relay()
        with tc.websocket_connect("/relay/agent") as ws:
            ws.send_json({"type": "auth", "key": "good-key", "models": ["m"]})
            assert ws.receive_json()["type"] == "auth_ok"
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

    def test_connections_are_capped(self) -> None:
        """The registry only ever counted authenticated tunnels — the population that
        isn't the problem. The cap counts sockets, pre-auth included.

        1013 (try again later) specifically. Without that assertion this test passes even
        with the cap deleted: the extra socket is then accepted and closed 1008 when its
        auth deadline lapses, which a bare `raises(Exception)` happily swallows. It caught
        the wrong rejection and looked green.
        """
        tc = _relay()
        with patch("app.relay._MAX_CONNECTIONS", 1), tc.websocket_connect("/relay/agent") as ws:
            ws.send_json({"type": "auth", "key": "good-key"})
            assert ws.receive_json()["type"] == "auth_ok"
            # The slot is taken; the next socket must be refused, not queued.
            with (
                pytest.raises(WebSocketDisconnect) as caught,
                tc.websocket_connect("/relay/agent") as second,
            ):
                second.receive_json()
            assert caught.value.code == 1013

    def test_the_cap_is_released_when_a_socket_closes(self) -> None:
        """Or the relay bricks itself after _MAX_CONNECTIONS lifetime connections."""
        tc = _relay()
        for _ in range(3):
            with tc.websocket_connect("/relay/agent") as ws:
                ws.send_json({"type": "auth", "key": "good-key"})
                assert ws.receive_json()["type"] == "auth_ok"
        # A fourth still gets in: the count went down each time.
        with tc.websocket_connect("/relay/agent") as ws:
            ws.send_json({"type": "auth", "key": "good-key"})
            assert ws.receive_json()["type"] == "auth_ok"

    def test_the_connection_cap_is_finite(self) -> None:
        assert 0 < _MAX_CONNECTIONS <= 10_000
