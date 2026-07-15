"""Relay server — persistent tunnels for NAT'd providers (Sessions 7.2-7.3).

Providers behind home routers can't accept inbound connections, so the agent opens ONE
persistent *outbound* WebSocket to this standalone relay and registers its provider id.
The relay keeps a ``provider_id → Tunnel`` registry so the coordinator can push a request
to a specific provider *through* its tunnel and read the reply — no public IP on the
provider.

Run standalone: ``uvicorn app.relay:app``.

Wire protocol (JSON frames):
  agent → relay:  {"type": "auth", "key": "grdx_..."}                first frame
  relay → agent:  {"type": "auth_ok", "provider_id": "..."}          on success
  agent → relay:  {"type": "ping"}  /  relay → agent: {"type":"pong"} keepalive
  relay → agent:  {"type": "request", "request_id", "job_id", "method", "payload"}
  agent → relay:  {"type": "response", "request_id", "status", "payload"}

Coordinator → relay is plain HTTP (``POST /relay/providers/{id}/request``), authenticated
with the shared internal secret; the relay bridges it onto the target tunnel.
"""

import asyncio
import hmac
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import ApiKey, OwnerType, Provider
from app.security import hash_api_key

Authenticator = Callable[[str], Awaitable[uuid.UUID | None]]

# Per-frame size cap on the relay WebSocket (security wave 3) — bound memory so a
# provider (or an attacker who obtained a provider key) can't OOM the relay with a
# giant frame.
_MAX_FRAME_BYTES = 1_048_576  # 1 MiB


async def _receive_json_bounded(ws: WebSocket) -> Any:
    """Receive one JSON text frame, rejecting anything over the size cap."""
    text = await ws.receive_text()
    if len(text.encode("utf-8", errors="ignore")) > _MAX_FRAME_BYTES:
        raise ValueError("relay frame exceeds size limit")
    return json.loads(text)


class TunnelClosedError(ConnectionError):
    """Raised on pending calls when a tunnel drops."""


class Tunnel:
    """A live provider connection with request/response correlation over one WebSocket."""

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws
        self._pending: dict[str, asyncio.Future] = {}

    async def call(self, *, job_id: str | None, method: str, payload: dict, timeout: float) -> dict:
        """Send a request through the tunnel and await the provider's response frame."""
        request_id = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = fut
        await self._ws.send_json(
            {
                "type": "request",
                "request_id": request_id,
                "job_id": job_id,
                "method": method,
                "payload": payload,
            }
        )
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(request_id, None)

    async def handle_incoming(self, msg: Any) -> None:
        """Dispatch an inbound frame from the agent (keepalive or a response)."""
        if not isinstance(msg, dict):
            return
        kind = msg.get("type")
        if kind == "ping":
            await self._ws.send_json({"type": "pong"})
        elif kind == "response":
            fut = self._pending.get(msg.get("request_id"))
            if fut is not None and not fut.done():
                fut.set_result(msg)

    def fail_all(self, exc: Exception) -> None:
        """Fail every in-flight call (called when the tunnel drops)."""
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)

    async def close(self) -> None:
        try:
            await self._ws.close(code=1000)
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup
            logger.debug("closing superseded tunnel failed: {}", exc)


class ConnectionRegistry:
    """Live ``provider_id → Tunnel`` map. Async-safe."""

    def __init__(self) -> None:
        self._tunnels: dict[uuid.UUID, Tunnel] = {}
        self._lock = asyncio.Lock()

    async def register(self, provider_id: uuid.UUID, tunnel: Tunnel) -> Tunnel | None:
        async with self._lock:
            old = self._tunnels.get(provider_id)
            self._tunnels[provider_id] = tunnel
            return old

    async def unregister(self, provider_id: uuid.UUID, tunnel: Tunnel) -> None:
        async with self._lock:
            if self._tunnels.get(provider_id) is tunnel:
                del self._tunnels[provider_id]

    async def get(self, provider_id: uuid.UUID) -> Tunnel | None:
        async with self._lock:
            return self._tunnels.get(provider_id)

    async def is_connected(self, provider_id: uuid.UUID) -> bool:
        return (await self.get(provider_id)) is not None

    async def count(self) -> int:
        async with self._lock:
            return len(self._tunnels)


registry = ConnectionRegistry()


async def resolve_provider(token: str) -> uuid.UUID | None:
    """Validate a provider API key against the database; return its provider id or None."""
    settings = get_settings()
    digest = hash_api_key(token, settings.api_hmac_key)
    async with get_sessionmaker()() as session:
        key = await session.scalar(select(ApiKey).where(ApiKey.key_hash == digest))
        if key is None or key.revoked or key.owner_type is not OwnerType.provider:
            return None
        if key.provider_id is None:
            return None
        provider = await session.get(Provider, key.provider_id)
        return provider.id if provider is not None else None


class RelayRequest(BaseModel):
    """A coordinator request to be bridged to a provider through its tunnel."""

    job_id: str | None = None
    method: str = "GET"
    payload: dict = Field(default_factory=dict)


class RelayResponse(BaseModel):
    """The provider's reply, unwrapped from the tunnel frame."""

    status: int
    payload: dict | None = None


async def require_internal(authorization: str | None = Header(default=None)) -> None:
    """Gate the coordinator→relay endpoint with the dedicated relay secret.

    Uses ``relay_key`` (not the API-key HMAC secret), compared in constant time.
    """
    settings = get_settings()
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip(), settings.relay_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="internal only")


def create_relay_app(authenticate: Authenticator | None = None) -> FastAPI:
    """Build the relay app. ``authenticate`` is injectable so tests can bypass the DB."""
    auth: Authenticator = authenticate or resolve_provider
    app = FastAPI(title="GRIDIX Relay", version="0.1.0")

    @app.get("/relay/health")
    async def relay_health() -> dict[str, int]:
        return {"tunnels": await registry.count()}

    @app.post("/relay/providers/{provider_id}/request", response_model=RelayResponse)
    async def relay_request(
        provider_id: uuid.UUID, body: RelayRequest, _: None = Depends(require_internal)
    ) -> RelayResponse:
        """Bridge a coordinator request onto a provider's tunnel and return its reply."""
        tunnel = await registry.get(provider_id)
        if tunnel is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="provider not connected",
            )
        try:
            frame = await tunnel.call(
                job_id=body.job_id,
                method=body.method,
                payload=body.payload,
                timeout=get_settings().relay_request_timeout,
            )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="provider did not respond"
            ) from exc
        except TunnelClosedError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="tunnel closed"
            ) from exc
        return RelayResponse(status=frame.get("status", 200), payload=frame.get("payload"))

    @app.websocket("/relay/agent")
    async def relay_agent(ws: WebSocket) -> None:
        await ws.accept()
        try:
            frame = await _receive_json_bounded(ws)
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

        tunnel = Tunnel(ws)
        # Register before confirming, so a client that sees auth_ok is already routable.
        superseded = await registry.register(provider_id, tunnel)
        if superseded is not None:
            await superseded.close()
        await ws.send_json({"type": "auth_ok", "provider_id": str(provider_id)})
        logger.info("relay tunnel up: provider {}", provider_id)

        try:
            while True:
                msg = await _receive_json_bounded(ws)
                await tunnel.handle_incoming(msg)
        except WebSocketDisconnect:
            pass
        except ValueError:
            # Oversized or malformed frame → drop the tunnel (1009 = message too big).
            await ws.close(code=1009)
        finally:
            tunnel.fail_all(TunnelClosedError("tunnel closed"))
            await registry.unregister(provider_id, tunnel)
            logger.info("relay tunnel down: provider {}", provider_id)

    return app


app = create_relay_app()
