"""Relay server — a persistent outbound tunnel for NAT'd providers (Session 7.2).

Providers behind home routers can't accept inbound connections, so the agent opens ONE
persistent *outbound* WebSocket to this standalone relay and registers its provider id.
The relay keeps a ``provider_id → live connection`` registry so the coordinator can later
(Session 7.3) push a request to a specific provider through its tunnel and read the reply.

Run standalone: ``uvicorn app.relay:app`` (a separate process from the API).

Wire protocol (JSON frames):
  agent → relay: {"type": "auth", "key": "grdx_..."}          first frame
  relay → agent: {"type": "auth_ok", "provider_id": "..."}    on success
  relay → agent: {"type": "auth_error", "reason": "..."}      then close
  agent ↔ relay: {"type": "ping"} / {"type": "pong"}          idle keepalive
Session 7.3 adds request/response frames (request_id, job_id, payload) on the same tunnel.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlalchemy import select

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import ApiKey, OwnerType, Provider
from app.security import hash_api_key

# An authenticator maps a presented key to a provider id (or None if invalid).
Authenticator = Callable[[str], Awaitable[uuid.UUID | None]]


class ConnectionRegistry:
    """Live ``provider_id → WebSocket`` tunnels. Async-safe."""

    def __init__(self) -> None:
        self._conns: dict[uuid.UUID, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def register(self, provider_id: uuid.UUID, ws: WebSocket) -> WebSocket | None:
        """Register a tunnel, returning the superseded connection (if any) to close."""
        async with self._lock:
            old = self._conns.get(provider_id)
            self._conns[provider_id] = ws
            return old

    async def unregister(self, provider_id: uuid.UUID, ws: WebSocket) -> None:
        """Remove a tunnel only if ``ws`` is still the registered one (no clobber)."""
        async with self._lock:
            if self._conns.get(provider_id) is ws:
                del self._conns[provider_id]

    async def get(self, provider_id: uuid.UUID) -> WebSocket | None:
        """Return the live tunnel for a provider, or None if not connected."""
        async with self._lock:
            return self._conns.get(provider_id)

    async def is_connected(self, provider_id: uuid.UUID) -> bool:
        return (await self.get(provider_id)) is not None

    async def count(self) -> int:
        async with self._lock:
            return len(self._conns)


registry = ConnectionRegistry()


async def resolve_provider(token: str) -> uuid.UUID | None:
    """Validate a provider API key against the database; return its provider id or None."""
    settings = get_settings()
    digest = hash_api_key(token, settings.secret_key)
    async with get_sessionmaker()() as session:
        key = await session.scalar(select(ApiKey).where(ApiKey.key_hash == digest))
        if key is None or key.revoked or key.owner_type is not OwnerType.provider:
            return None
        if key.provider_id is None:
            return None
        provider = await session.get(Provider, key.provider_id)
        return provider.id if provider is not None else None


def create_relay_app(authenticate: Authenticator | None = None) -> FastAPI:
    """Build the relay app. ``authenticate`` is injectable so tests can bypass the DB."""
    auth: Authenticator = authenticate or resolve_provider
    app = FastAPI(title="GRIDIX Relay", version="0.1.0")

    @app.get("/relay/health")
    async def relay_health() -> dict[str, int]:
        return {"tunnels": await registry.count()}

    @app.websocket("/relay/agent")
    async def relay_agent(ws: WebSocket) -> None:
        await ws.accept()
        try:
            frame = await ws.receive_json()
        except (WebSocketDisconnect, ValueError):
            await ws.close(code=1008)
            return

        if not isinstance(frame, dict) or frame.get("type") != "auth" or not frame.get("key"):
            await ws.send_json({"type": "auth_error", "reason": "expected auth frame"})
            await ws.close(code=1008)
            return

        provider_id = await auth(frame["key"])
        if provider_id is None:
            await ws.send_json({"type": "auth_error", "reason": "invalid key"})
            await ws.close(code=1008)
            return

        # Register before confirming, so a client that sees auth_ok is already routable.
        superseded = await registry.register(provider_id, ws)
        if superseded is not None:
            await _safe_close(superseded)
        await ws.send_json({"type": "auth_ok", "provider_id": str(provider_id)})
        logger.info("relay tunnel up: provider {}", provider_id)

        try:
            while True:
                msg = await ws.receive_json()
                if isinstance(msg, dict) and msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
                # Session 7.3 handles request/response frames here.
        except WebSocketDisconnect:
            pass
        finally:
            await registry.unregister(provider_id, ws)
            logger.info("relay tunnel down: provider {}", provider_id)

    return app


async def _safe_close(ws: WebSocket) -> None:
    """Close a superseded tunnel, ignoring errors if it's already gone."""
    try:
        await ws.close(code=1000)
    except Exception as exc:  # noqa: BLE001 - best-effort cleanup
        logger.debug("closing superseded tunnel failed: {}", exc)


app = create_relay_app()
