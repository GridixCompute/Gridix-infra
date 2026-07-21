"""Relay server — persistent tunnels for NAT'd providers (Sessions 7.2-7.3).

Providers behind home routers can't accept inbound connections, so the agent opens ONE
persistent *outbound* WebSocket to this standalone relay and registers its provider id.
The relay keeps a ``provider_id → Tunnel`` registry so the coordinator can push a request
to a specific provider *through* its tunnel and read the reply — no public IP on the
provider.

Run standalone: ``uvicorn app.relay:app``.

Wire protocol (JSON frames):
  agent → relay:  {"type": "auth", "key": "grdx_...", "models": ["llama-3-70b", ...]}
                                                                     first frame
  relay → agent:  {"type": "auth_ok", "provider_id": "..."}          on success
  agent → relay:  {"type": "ping"}  /  relay → agent: {"type":"pong"} keepalive
  relay → agent:  {"type": "request", "request_id", "job_id", "method", "payload",
                   "stream": bool}
  agent → relay:  {"type": "response", "request_id", "status", "payload"}   terminal, always
  agent → relay:  {"type": "chunk", "request_id", "delta", "tokens"}        streaming only
  relay → agent:  {"type": "cancel", "request_id"}                          stop generating

Coordinator → relay is plain HTTP, authenticated with the shared internal secret:

  POST /relay/providers/{id}/request   one reply, JSON            (unary)
  POST /relay/providers/{id}/stream    many frames, NDJSON        (streaming)

Streaming is the reason ``Tunnel`` holds two correlation maps rather than one. The unary
path resolves a single future per ``request_id``; a streamed request cannot, because the
node emits an unbounded number of frames before its terminal one, and forwarding them only
after the last has arrived is not streaming — it is a slow unary call. So a streamed
request registers a QUEUE instead, the receive loop pushes each frame onto it, and the
bridge drains it as frames arrive.

``cancel`` is the half that makes disconnects safe. A streamed generation is the one
request that keeps costing a provider money after the caller has stopped listening, so
when the coordinator stops reading, the relay tells the node to stop generating. Without
it a closed browser tab would leave a GPU running to the end of its token budget with
nobody to send the result to.
"""

import asyncio
import hmac
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing, asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.config import get_settings
from app.db import get_sessionmaker
from app.logging import configure_logging
from app.models import ApiKey, OwnerType, Provider, ProviderModel
from app.presence import mark_seen
from app.ratelimit import auth_failures_exceeded, record_auth_failure
from app.secret_manager import init_secrets
from app.security import hash_api_key

Authenticator = Callable[[str], Awaitable[uuid.UUID | None]]

# Per-frame size cap on the relay WebSocket (security wave 3) — bound memory so a
# provider (or an attacker who obtained a provider key) can't OOM the relay with a
# giant frame.
_MAX_FRAME_BYTES = 1_048_576  # 1 MiB

# Bounds on the declared model list. A node names what it serves; nothing stops a
# compromised one from naming ten thousand models to bloat the registry.
_MAX_MODELS = 64
_MAX_MODEL_NAME = 128

# How long an accepted socket may stay silent before it must have authenticated.
# Without this, `await ws.accept()` then an unbounded receive parks the coroutine forever:
# connect, send nothing, hold. Such a socket is pre-auth, so it is in no registry and
# counted by nothing — N of them cost an attacker nothing and cost the relay its file
# descriptors. Generous enough for a slow link, far short of forever.
_AUTH_TIMEOUT_SECONDS = 10.0

# Ceiling on sockets held at once, PRE-AUTH INCLUDED. The registry only ever counted
# authenticated tunnels, which is precisely the population that isn't the problem.
_MAX_CONNECTIONS = 512

# Frames a streamed request may have buffered in the relay before the coordinator has read
# them. The queue exists because the tunnel's receive loop must never block: awaiting a slow
# consumer there would stall every other request sharing the socket. Bounding it is what
# stops a node that generates faster than the coordinator reads (or one that floods
# deliberately) from growing the relay's memory without limit — the same reasoning as the
# 1 MiB frame cap, applied to frame COUNT rather than frame size, which that cap does not
# bound at all. On overflow the stream is terminated rather than silently trimmed: dropping
# chunks would under-report the tokens the request is billed on.
_MAX_STREAM_QUEUE_FRAMES = 1024

# Live sockets, authenticated or not. Guards the accept path, so it has to be counted
# where sockets are accepted rather than where tunnels are registered.
_connections = 0


def _idle_timeout() -> float:
    """How long a live tunnel may stay silent before we assume it is gone.

    Derived from the agent's keepalive cadence rather than a constant of its own: the
    agent pings on a schedule, so anything past a few missed beats is a dead peer. Tying
    them together means one knob moves both, instead of a timeout that quietly contradicts
    the heartbeat interval.
    """
    return max(30.0, get_settings().agent_heartbeat_interval_seconds * 3.0)


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
        self._streams: dict[str, asyncio.Queue] = {}

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
                "stream": False,
            }
        )
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(request_id, None)

    async def stream(
        self, *, job_id: str | None, method: str, payload: dict, timeout: float
    ) -> AsyncIterator[dict]:
        """Send a streamed request and yield each frame the node sends back, as it arrives.

        Yields ``chunk`` frames until a terminal ``response`` frame, which is yielded last.
        ``timeout`` bounds the gap BETWEEN frames rather than the whole generation: a stream
        may legitimately run far longer than a unary call, but a node that has gone silent
        for the timeout is gone, and the caller must not wait on it forever.

        The ``finally`` is the load-bearing part. Whatever ends the iteration early — the
        consumer disconnecting, a timeout, the tunnel dropping — the node is told to stop.
        A generation nobody is reading is pure cost to the provider, and the node cannot see
        that the far end went away; only the relay can.
        """
        request_id = uuid.uuid4().hex
        queue: asyncio.Queue = asyncio.Queue(maxsize=_MAX_STREAM_QUEUE_FRAMES)
        self._streams[request_id] = queue
        await self._ws.send_json(
            {
                "type": "request",
                "request_id": request_id,
                "job_id": job_id,
                "method": method,
                "payload": payload,
                "stream": True,
            }
        )
        finished = False
        try:
            while True:
                frame = await asyncio.wait_for(queue.get(), timeout)
                if frame.get("type") == "chunk":
                    yield frame
                    continue
                # Anything that is not a chunk ends the stream: the node's terminal
                # `response`, or an `error` the relay itself synthesised.
                finished = True
                yield frame
                return
        finally:
            self._streams.pop(request_id, None)
            if not finished:
                await self._cancel(request_id)

    async def _cancel(self, request_id: str) -> None:
        """Best-effort 'stop generating' for a stream that ended before the node finished.

        Never raises. This runs in a ``finally`` on paths where the tunnel may already be
        dead or the surrounding task already cancelled, and an exception here would mask the
        real reason the stream ended — or, worse, escape into the billing ``finally`` that
        has to run next.
        """
        try:
            await self._ws.send_json({"type": "cancel", "request_id": request_id})
        except Exception as exc:  # noqa: BLE001 - best-effort on a possibly-dead socket
            logger.debug("cancel for {} not delivered: {}", request_id, exc)

    async def handle_incoming(self, msg: Any) -> None:
        """Dispatch an inbound frame from the agent (keepalive, chunk, or response)."""
        if not isinstance(msg, dict):
            return
        kind = msg.get("type")
        if kind == "ping":
            await self._ws.send_json({"type": "pong"})
            return
        if kind not in ("chunk", "response"):
            return

        request_id = msg.get("request_id")
        queue = self._streams.get(request_id)
        if queue is not None:
            self._offer(request_id, queue, msg)
            return
        # Not a stream: the unary path, unchanged. A `chunk` for an unknown request_id
        # falls through to nothing, which is what a late frame from a cancelled stream is.
        if kind == "response":
            fut = self._pending.get(request_id)
            if fut is not None and not fut.done():
                fut.set_result(msg)

    def _offer(self, request_id: str, queue: asyncio.Queue, frame: dict) -> None:
        """Hand a frame to a waiting stream without ever blocking the receive loop.

        On overflow the stream is ended with an error instead of dropping the frame. A
        dropped chunk is not a cosmetic loss: the coordinator bills on the tokens it saw, so
        silently discarding them would under-charge for work the provider really did.
        """
        try:
            queue.put_nowait(frame)
        except asyncio.QueueFull:
            logger.warning("stream {} exceeded {} buffered frames", request_id, queue.maxsize)
            self._streams.pop(request_id, None)
            with suppress(asyncio.QueueEmpty):
                queue.get_nowait()  # make room for the terminal frame
            with suppress(asyncio.QueueFull):
                queue.put_nowait({"type": "error", "error": "stream exceeded the relay's buffer"})

    def fail_all(self, exc: Exception) -> None:
        """Fail every in-flight call and stream (called when the tunnel drops)."""
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        # A stream cannot take an exception the way a future can — it is being drained by a
        # `queue.get()`. Push a terminal error instead, so the consumer stops promptly rather
        # than waiting out the inter-frame timeout on a socket that is already gone.
        for request_id, queue in list(self._streams.items()):
            self._streams.pop(request_id, None)
            with suppress(asyncio.QueueFull):
                queue.put_nowait({"type": "error", "error": str(exc) or "tunnel closed"})

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


def _clean_models(raw: Any) -> list[str]:
    """Normalise the model list off an auth frame. Untrusted input — bound everything.

    Silently drops anything malformed rather than refusing the tunnel: a node with one bad
    entry should still serve the models it named correctly, and the registry is a claim to
    be checked by canaries, not a security boundary.
    """
    if not isinstance(raw, list):
        return []
    models = []
    for item in raw[:_MAX_MODELS]:
        if isinstance(item, str) and 0 < len(item) <= _MAX_MODEL_NAME:
            models.append(item.strip())
    return sorted({m for m in models if m})


async def record_models(provider_id: uuid.UUID, models: list[str]) -> None:
    """Replace the provider's declared model set.

    Replace, not merge: the tunnel that just came up is the current truth about what this
    node serves. A model it no longer runs must stop being dispatched to it, and a stale
    row would keep sending work to a node that will only fail it.
    """
    async with get_sessionmaker()() as session:
        await session.execute(delete(ProviderModel).where(ProviderModel.provider_id == provider_id))
        session.add_all(ProviderModel(provider_id=provider_id, model=m) for m in models)
        await session.commit()


async def mark_provider_seen(provider_id: uuid.UUID) -> None:
    """Stamp presence so the coordinator's node selection can see this node as live."""
    settings = get_settings()
    async with get_sessionmaker()() as session:
        provider = await session.get(Provider, provider_id)
        if provider is None:
            return
        mark_seen(provider, datetime.now(UTC), settings.connection_timeout_seconds)
        await session.commit()


async def clear_models(provider_id: uuid.UUID) -> None:
    """Drop the node's model claims when its tunnel goes down.

    Without this a dead node stays selectable until presence ages out, and every request
    routed to it fails on the bridge. Dropping the claim at disconnect makes selection
    skip it immediately.
    """
    async with get_sessionmaker()() as session:
        await session.execute(delete(ProviderModel).where(ProviderModel.provider_id == provider_id))
        await session.commit()


async def resolve_provider(token: str) -> uuid.UUID | None:
    """Validate a provider API key against the database; return its provider id or None."""
    settings = get_settings()
    try:
        digest = hash_api_key(token, settings.api_hmac_key)
    except ValueError:
        return None  # too long to be a key we issued — never hash it (L1)
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate secrets and transport before the relay serves anything.

    The relay is a fourth process, and until now the only one that never ran this. The
    API, scheduler and chain worker all call init_secrets at startup; this one built its
    app at import time with no hook, so neither validate_secret_config nor
    validate_tls_config ever fired here.

    That was not a missing nicety. `relay_key` falls back to `secret_key` (config.py),
    whose default is the published constant "dev-insecure-secret-change-me" — so a relay
    deployed with only GRIDIX_SECRET_KEY set authenticated its internal bridge on a value
    printed in this repository. Anyone who could reach the bridge could push arbitrary
    requests down any connected provider's tunnel. The Vault case was worse still: an
    operator who put GRIDIX_RELAY_SECRET in Vault got a relay that never read Vault and
    silently kept using the constant.
    """
    configure_logging()
    settings = get_settings()
    init_secrets(settings)
    logger.info("GRIDIX relay starting (env={})", settings.env)
    yield


def create_relay_app(authenticate: Authenticator | None = None) -> FastAPI:
    """Build the relay app. ``authenticate`` is injectable so tests can bypass the DB."""
    auth: Authenticator = authenticate or resolve_provider
    app = FastAPI(title="GRIDIX Relay", version="0.1.0", lifespan=lifespan)

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

    @app.post("/relay/providers/{provider_id}/stream")
    async def relay_stream(
        provider_id: uuid.UUID, body: RelayRequest, _: None = Depends(require_internal)
    ) -> StreamingResponse:
        """Bridge a STREAMED request onto a provider's tunnel, forwarding frames as they come.

        NDJSON (one JSON frame per line) rather than SSE: this hop is relay → coordinator,
        and the coordinator re-shapes what it reads into OpenAI SSE for the developer.
        Emitting SSE here would mean parsing and re-emitting the same envelope twice, and
        would tempt a future caller into forwarding these bytes to a client verbatim —
        which would leak the internal frame shape into the public contract.

        Errors are frames, not status codes. The status line is committed the moment the
        first byte is sent, so a node that dies mid-generation cannot be reported as an HTTP
        error; the coordinator has to be able to tell "the node failed" from "the node
        finished", and after streaming has begun the only channel left is the body.
        """
        tunnel = await registry.get(provider_id)
        if tunnel is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="provider not connected",
            )

        async def frames() -> AsyncIterator[str]:
            timeout = get_settings().relay_request_timeout
            # `aclosing` is what makes disconnect propagate. Without it, abandoning this
            # generator leaves the inner one for the garbage collector, and the node keeps
            # generating until it finishes — the exact cost this endpoint exists to stop.
            try:
                async with aclosing(
                    tunnel.stream(
                        job_id=body.job_id,
                        method=body.method,
                        payload=body.payload,
                        timeout=timeout,
                    )
                ) as stream:
                    async for frame in stream:
                        yield json.dumps(frame) + "\n"
            except TimeoutError:
                yield json.dumps({"type": "error", "error": "provider did not respond"}) + "\n"
            except TunnelClosedError:
                yield json.dumps({"type": "error", "error": "tunnel closed"}) + "\n"

        return StreamingResponse(
            frames(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @app.websocket("/relay/agent")
    async def relay_agent(ws: WebSocket) -> None:
        # CSWSH guard (H7): the agent is a non-browser client and sends no Origin. A browser
        # page always sends one, so a cross-site page that tries to open the tunnel is rejected
        # here (before accept, so it never reaches auth) unless its Origin is explicitly
        # allowlisted. Fail-closed: any present-but-unlisted Origin is refused.
        origin = ws.headers.get("origin")
        if origin is not None and origin not in get_settings().relay_allowed_origins_list:
            logger.warning("relay tunnel rejected: disallowed Origin {!r}", origin)
            await ws.close(code=1008)
            return

        global _connections
        if _connections >= _MAX_CONNECTIONS:
            # 1013 = try again later. Refused before accept, so a flood costs one
            # handshake rather than a held socket.
            logger.warning("relay at capacity ({} sockets), refusing tunnel", _connections)
            await ws.close(code=1013)
            return

        # Brute-force guard (H8): a failed auth frame used to cost the attacker nothing, so
        # keys could be guessed over the tunnel at connection rate — and each guess spent a
        # DB round-trip (resolve_provider), making it an amplifier too. Check the IP's
        # failure budget BEFORE accepting, so a locked-out client never reaches the DB.
        #
        # Beside the capacity cap above, not instead of it: that one bounds how many sockets
        # exist, this one bounds how many guesses come down them. Neither covers the other.
        client = ws.client
        ip_identity = f"relay-auth:ip:{client.host if client else 'unknown'}"
        settings = get_settings()
        if await auth_failures_exceeded(ip_identity, settings.relay_auth_failures_per_minute):
            logger.warning("relay tunnel rejected: failed-auth budget spent by {}", ip_identity)
            await ws.close(code=1008)
            return

        await ws.accept()
        _connections += 1
        try:
            await _serve_tunnel(ws, auth, ip_identity)
        finally:
            _connections -= 1

    async def _serve_tunnel(ws: WebSocket, auth: Authenticator, ip_identity: str) -> None:
        """Authenticate the socket, then pump its frames until it goes away.

        ``ip_identity`` is threaded through from the accept path so a failed key can be
        charged to the budget that refused it there (H8) — the check and the record have to
        name the same client, or the budget never fills and the guard never fires.
        """
        try:
            # A socket that never authenticates must not be able to hold a slot forever.
            frame = await asyncio.wait_for(_receive_json_bounded(ws), timeout=_AUTH_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning("relay tunnel: no auth frame within {}s", _AUTH_TIMEOUT_SECONDS)
            await ws.close(code=1008)
            return
        except (WebSocketDisconnect, ValueError):
            await ws.close(code=1008)
            return

        if not isinstance(frame, dict) or frame.get("type") != "auth" or not frame.get("key"):
            await ws.send_json({"type": "auth_error", "reason": "expected auth frame"})
            await ws.close(code=1008)
            return

        provider_id = await auth(frame["key"])
        if provider_id is None:
            await record_auth_failure(ip_identity)
            await ws.send_json({"type": "auth_error", "reason": "invalid key"})
            await ws.close(code=1008)
            return

        tunnel = Tunnel(ws)
        # Register before confirming, so a client that sees auth_ok is already routable.
        superseded = await registry.register(provider_id, tunnel)
        if superseded is not None:
            await superseded.close()
        # Publish what this node serves, and that it is live, before confirming: a node
        # that has seen auth_ok is dispatchable, so the coordinator must already be able
        # to find it. Doing this after would leave a window where the node is routable
        # but invisible to selection.
        models = _clean_models(frame.get("models"))
        await record_models(provider_id, models)
        await mark_provider_seen(provider_id)
        await ws.send_json({"type": "auth_ok", "provider_id": str(provider_id)})
        logger.info("relay tunnel up: provider {} serving {}", provider_id, models or "no models")

        try:
            while True:
                # An authenticated tunnel that goes silent holds a slot just as well as an
                # unauthenticated one. The agent keepalives (relay answers `ping`), so
                # silence past the idle deadline means the far end is gone without a
                # close frame — a half-open TCP connection the OS hasn't noticed.
                msg = await asyncio.wait_for(_receive_json_bounded(ws), timeout=_idle_timeout())
                # A keepalive also refreshes presence. Dispatch selects nodes by the DB
                # `last_seen` window (presence.is_connected), not by this in-memory tunnel
                # registry — and only auth ever stamped it, so a connected node went
                # undispatchable `connection_timeout_seconds` after connecting even with the
                # tunnel wide open. The agent pings well inside that window, so refreshing on
                # each ping keeps a live node selectable, at one small UPDATE per ping.
                if isinstance(msg, dict) and msg.get("type") == "ping":
                    await mark_provider_seen(provider_id)
                await tunnel.handle_incoming(msg)
        except TimeoutError:
            logger.info("relay tunnel idle past {}s: provider {}", _idle_timeout(), provider_id)
            await ws.close(code=1001)
        except WebSocketDisconnect:
            pass
        except ValueError:
            # Oversized or malformed frame → drop the tunnel (1009 = message too big).
            await ws.close(code=1009)
        finally:
            tunnel.fail_all(TunnelClosedError("tunnel closed"))
            await registry.unregister(provider_id, tunnel)
            # Only retract the claims if this tunnel is still the current one. A
            # reconnect supersedes the old tunnel and re-registers first; clearing here
            # unconditionally would erase the LIVE node's models as the dead one unwinds.
            if not await registry.is_connected(provider_id):
                await clear_models(provider_id)
            logger.info("relay tunnel down: provider {}", provider_id)

    return app


app = create_relay_app()
