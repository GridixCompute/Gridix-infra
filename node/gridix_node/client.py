"""Thin GRIDIX inference node: a relay WebSocket client backed by a local Ollama server.

Reconstructed from the relay contract in ``api/app/relay.py`` + ``api/app/dispatch.py`` and
the M4 end-to-end bring-up (developer → coordinator → relay → this node → Ollama → back).
The wire protocol this implements, taken from ``relay.py`` (not from prose):

  node → relay:  {"type": "auth", "key": "grdx_...", "models": [...]}   first frame, <=10s
  relay → node:  {"type": "auth_ok", "provider_id": "..."}                              (on success)
                 {"type": "auth_error", "reason": "..."}                                (on failure)
  node → relay:  {"type": "ping"}   relay → node: {"type": "pong"}                       (keepalive)
  relay → node:  {"type": "request", "request_id", "job_id", "method", "payload", "stream"}
  node → relay:  {"type": "response", "request_id": <echoed>, "status": 200,
                  "payload": {"content": "...", "usage": {"prompt_tokens", "completion_tokens"}}}
  node → relay:  {"type": "chunk", "request_id", "delta": "...", "tokens": <cumulative>}
  relay → node:  {"type": "cancel", "request_id"}

When ``stream`` is true the node emits ``chunk`` frames as Ollama produces tokens and then
one terminal ``response`` frame carrying the usage totals — the same terminal frame the
unary path sends, so the coordinator has one shape to bill from either way.

``cancel`` is honoured because the node is the only place that can actually stop the work.
The coordinator learns a client hung up and the relay forwards that down the tunnel, but
until this loop cancels the task, Ollama keeps generating to the end of its token budget on
a request whose output nobody will ever read. ``tokens`` rides each chunk so the coordinator
can bill a cancelled stream for what was really produced rather than guessing.

The node advertises the *catalogue* model ids it serves (``api/app/catalog.py``) and maps each
to the Ollama tag it actually runs. It answers ``chat.completions`` only; anything else — an
unmapped model, ``images.generations`` (Ollama cannot generate images), or an Ollama failure —
comes back as a ``status >= 400`` response, never a crashed loop (``dispatch.py`` turns a
``status >= 400`` into a DispatchError, so the coordinator charges nothing).

Configuration is entirely by environment (nothing hardcoded):
  GRIDIX_RELAY_URL   ws URL of the relay's /relay/agent endpoint, e.g. ws://localhost:8100/relay/agent
  GRIDIX_NODE_KEY    the provider API key (grdx_...) issued by the coordinator
  OLLAMA_URL         Ollama's OpenAI-compatible chat endpoint (default below)
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx
import websockets

# Catalogue id (what the coordinator dispatches, see api/app/catalog.py) → Ollama model tag.
# Extend this as the node is taught to serve more chat models; every key here is advertised
# to the relay in the auth frame, so the coordinator only ever routes ids the node can map.
# Maps a coordinator catalogue id to the Ollama tag this node actually runs. The node
# advertises every key here to the relay (record_models writes one ProviderModel row per
# key), and select_node routes on those ids — so a key for a model this node's Ollama has
# NOT pulled makes the node falsely claim to serve it and 404 when dispatched one. Map only
# what is pulled.
#
# Just the public free tier's model for now: FREE_CHAT_MODEL = "llama3.2-3b" (see
# api/app/free_tier.py) is the id select_node matches on, "llama3.2:3b" the Ollama tag. The
# paid 8B (catalogue id "llama-3.1-8b") is intentionally absent — re-add it the day a node
# actually runs `ollama pull llama3.1:8b`, not before.
#
# On the node host: `ollama pull llama3.2:3b`, and set OLLAMA_NUM_PARALLEL to the
# coordinator's `free_chat_concurrency` — more slots there than the node has parallelism just
# moves the queue to where nobody can measure it; fewer wastes the small model's headroom.
MODEL_MAP: dict[str, str] = {
    "llama3.2-3b": "llama3.2:3b",
}

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/v1/chat/completions"

# Image models this node serves (catalogue ids the coordinator dispatches, see
# api/app/catalog.py). Advertised alongside MODEL_MAP's chat ids, and served by a SEPARATE
# backend — a diffusers server reached over HTTP — because image generation needs torch and a
# GPU where chat needs neither. Empty unless an image server is actually reachable.
IMAGE_MODELS: list[str] = ["sdxl-turbo"]
IMAGE_SERVER_URL = os.environ.get("IMAGE_SERVER_URL", "http://127.0.0.1:8500/generate")

# The node returns the generated image INLINE as base64 (by-value): it has no credential to
# upload to the coordinator's blob store, so the coordinator decodes and stores it. The whole
# response frame must stay under the relay's cap, so the encoded image is bounded well below
# MAX_FRAME_BYTES to leave room for the JSON envelope. A 512x512 PNG is ~0.5 MiB encoded — the
# image server is what keeps generation at that size; this is the node's backstop.
MAX_IMAGE_B64_BYTES = 1_000_000

# The relay closes a silent tunnel after ``max(30, heartbeat*3)`` seconds (relay.py
# ``_idle_timeout``); ping well inside that so a node serving no traffic stays connected.
PING_INTERVAL_SECONDS = 10.0
# Mirror relay.py ``_MAX_FRAME_BYTES`` so the client rejects oversized frames symmetrically.
MAX_FRAME_BYTES = 1_048_576
# A single Ollama completion should finish well within this; it bounds a wedged backend.
OLLAMA_TIMEOUT_SECONDS = 120.0


class NodeAuthError(RuntimeError):
    """The relay rejected the auth frame (bad key, or not an auth_ok reply)."""


class _UnknownModelError(Exception):
    """The dispatched catalogue id is not in MODEL_MAP — the node cannot serve it."""

    def __init__(self, model: object) -> None:
        super().__init__(str(model))
        self.model = model


@dataclass
class Config:
    relay_url: str
    node_key: str
    ollama_url: str = DEFAULT_OLLAMA_URL
    models: list[str] = field(default_factory=lambda: list(MODEL_MAP) + IMAGE_MODELS)
    ping_interval: float = PING_INTERVAL_SECONDS


def load_config() -> Config:
    """Build the node config from the environment. Raises KeyError if a required var is unset."""
    return Config(
        relay_url=os.environ["GRIDIX_RELAY_URL"],
        node_key=os.environ["GRIDIX_NODE_KEY"],
        ollama_url=os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL),
        models=list(MODEL_MAP) + IMAGE_MODELS,
    )


def _response(request_id: object, status: int, payload: dict) -> dict:
    """A relay ``response`` frame. ``request_id`` is echoed so the relay correlates the reply."""
    return {"type": "response", "request_id": request_id, "status": status, "payload": payload}


def _chunk(request_id: object, delta: str, tokens: int) -> dict:
    """A relay ``chunk`` frame — one slice of a streamed completion.

    ``tokens`` is CUMULATIVE, not per-chunk: a coordinator that misses or drops a frame
    still bills the right total, and a cancelled stream is billed on the last count that
    actually arrived rather than on a running sum the two ends could disagree about.
    """
    return {"type": "chunk", "request_id": request_id, "delta": delta, "tokens": tokens}


def _ollama_body(payload: dict, *, stream: bool) -> tuple[str, dict]:
    """The Ollama request for a chat payload. Raises ``_UnknownModelError`` for an unmapped id."""
    catalogue_id = payload.get("model")
    ollama_model = MODEL_MAP.get(catalogue_id) if isinstance(catalogue_id, str) else None
    if ollama_model is None:
        raise _UnknownModelError(catalogue_id)

    body: dict = {"model": ollama_model, "messages": payload.get("messages", []), "stream": stream}
    # Forward the tuning knobs the coordinator passed through, when present.
    for key in ("max_tokens", "temperature", "seed"):
        if payload.get(key) is not None:
            body[key] = payload[key]
    return ollama_model, body


async def _run_chat(payload: dict, ollama_url: str, http: httpx.AsyncClient) -> dict:
    """Serve one chat.completions payload via Ollama; return the coordinator's payload dict.

    The reply payload is exactly what ``inference.py`` reads: ``content`` (choices[0].message)
    and ``usage`` with ``prompt_tokens``/``completion_tokens`` (used to bill the request).
    Raises ``_UnknownModelError`` for an unmapped id and httpx/parse errors for a bad backend;
    the caller turns both into a ``status >= 400`` response.
    """
    _, body = _ollama_body(payload, stream=False)
    resp = await http.post(ollama_url, json=body)
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage") or {}
    return {
        "content": data["choices"][0]["message"]["content"],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        },
    }


def _delta_of(event: dict) -> str:
    """The text carried by one Ollama stream event, or "" if it carries none.

    Defensive about every level: a backend that returns a malformed event must not kill a
    stream that has already delivered tokens the coordinator will bill for.
    """
    choices = event.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    return content if isinstance(content, str) else ""


async def _stream_chat(
    payload: dict,
    ollama_url: str,
    http: httpx.AsyncClient,
    send: Callable[[dict], Awaitable[None]],
    request_id: object,
) -> dict:
    """Stream one chat.completions payload from Ollama, emitting chunk frames as it goes.

    Returns the terminal payload (content + usage) for the caller to send as ``response``.
    Cancellation propagates out of the ``async for``: the ``async with`` closes the HTTP
    response, which drops the connection to Ollama and stops the generation. That is the
    whole point of streaming from the backend rather than buffering — a cancelled request
    stops costing the GPU immediately instead of running to its token limit.
    """
    _, body = _ollama_body(payload, stream=True)

    pieces: list[str] = []
    tokens = 0
    usage: dict = {}

    async with http.stream("POST", ollama_url, json=body) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            # Ollama reports usage on a final event when it reports it at all.
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
            delta = _delta_of(event)
            if not delta:
                continue
            pieces.append(delta)
            # One event is one token from a llama.cpp-family backend. Where the backend
            # reports real counts they win on the terminal frame below; this keeps a
            # cancelled stream billable with no backend cooperation at all.
            tokens += 1
            await send(_chunk(request_id, delta, tokens))

    return {
        "content": "".join(pieces),
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", tokens),
        },
    }


async def handle_stream_request(
    frame: dict,
    ollama_url: str,
    http: httpx.AsyncClient,
    send: Callable[[dict], Awaitable[None]],
) -> dict:
    """Serve one streamed request, returning the terminal ``response`` frame to send.

    Never raises for a backend failure — the coordinator has to be able to tell "the node
    failed" from "the node finished", and after chunks have been sent the only way to say so
    is a terminal frame carrying a failure status.
    """
    request_id = frame.get("request_id")
    payload = frame.get("payload") or {}
    try:
        result = await _stream_chat(payload, ollama_url, http, send, request_id)
    except _UnknownModelError as exc:
        return _response(request_id, 400, {"error": f"model {exc.model!r} not served by this node"})
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        return _response(request_id, 502, {"error": f"ollama backend error: {exc}"})
    return _response(request_id, 200, result)


async def _run_image(payload: dict, http: httpx.AsyncClient) -> dict:
    """Generate an image via the local image server; return ``{"images": [<base64 PNG>]}``.

    By-value transport: the image is returned INLINE as base64, not a URL. A node has no
    credential to upload to the coordinator's blob store, and a node-hosted URL would be
    unreachable by a browser and would die with the node — so the coordinator decodes and
    stores the bytes instead. The encoded image is bounded (``MAX_IMAGE_B64_BYTES``) so the
    response frame stays under the relay cap; an oversized image is refused, not truncated.

    Raises ``_UnknownModelError`` for an image id this node does not serve (the coordinator
    should never route one, but a node must not answer for a model it didn't advertise).
    """
    model = payload.get("model")
    if model not in IMAGE_MODELS:
        raise _UnknownModelError(model)
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("image payload missing prompt")

    resp = await http.post(
        IMAGE_SERVER_URL, json={"prompt": prompt}, timeout=OLLAMA_TIMEOUT_SECONDS
    )
    resp.raise_for_status()
    image_b64 = resp.json()["image_b64"]
    if not isinstance(image_b64, str) or not image_b64:
        raise ValueError("image server returned no image")
    if len(image_b64) > MAX_IMAGE_B64_BYTES:
        # Would overflow the relay frame. The image server bounds size at 512x512; this is the
        # node's backstop so a misconfigured server can't wedge the tunnel with a dropped frame.
        raise ValueError(
            f"image too large for relay frame: {len(image_b64)} > {MAX_IMAGE_B64_BYTES}"
        )
    return {"images": [image_b64]}


async def handle_request(frame: dict, ollama_url: str, http: httpx.AsyncClient) -> dict:
    """Turn one relay ``request`` frame into the ``response`` frame to send back.

    Never raises: every failure path becomes a ``status >= 400`` response so the receive loop
    keeps running and the coordinator charges nothing for a request the node could not serve.
    """
    request_id = frame.get("request_id")
    method = frame.get("method")
    payload = frame.get("payload") or {}

    if method == "images.generations":
        try:
            result = await _run_image(payload, http)
        except _UnknownModelError as exc:
            return _response(request_id, 400, {"error": f"model {exc.model!r} not served"})
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            return _response(request_id, 502, {"error": f"image backend error: {exc}"})
        return _response(request_id, 200, result)

    if method != "chat.completions":
        return _response(request_id, 501, {"error": f"method {method!r} not served"})

    try:
        result = await _run_chat(payload, ollama_url, http)
    except _UnknownModelError as exc:
        return _response(request_id, 400, {"error": f"model {exc.model!r} not served by this node"})
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        return _response(request_id, 502, {"error": f"ollama backend error: {exc}"})
    return _response(request_id, 200, result)


async def _authenticate(ws, config: Config) -> str:
    """Send the auth frame and wait for auth_ok; return the provider_id. Raises NodeAuthError."""
    await ws.send(json.dumps({"type": "auth", "key": config.node_key, "models": config.models}))
    ack = json.loads(await ws.recv())
    if not isinstance(ack, dict) or ack.get("type") != "auth_ok":
        reason = ack.get("reason", ack) if isinstance(ack, dict) else ack
        raise NodeAuthError(f"relay refused auth: {reason}")
    return ack.get("provider_id")


async def _ping_forever(ws, interval: float) -> None:
    """Keep the tunnel alive; the relay refreshes presence on each ping and answers pong."""
    while True:
        await asyncio.sleep(interval)
        await ws.send(json.dumps({"type": "ping"}))


async def _serve(ws, config: Config, http: httpx.AsyncClient, stop_after: int | None) -> None:
    """Pump frames: reply to each request, ignore pongs, until the relay closes (or stop_after)."""
    ping = asyncio.create_task(_ping_forever(ws, config.ping_interval))
    inflight: set[asyncio.Task] = set()
    # Streamed requests are tracked by id so `cancel` can reach the right one. A unary
    # request is not cancellable — it is one call that either lands or doesn't — so only
    # streams go in here.
    streams: dict[object, asyncio.Task] = {}
    served = 0

    # One writer at a time: chunk frames race the terminal frame and the keepalive on a
    # single socket, and websockets does not promise interleaved sends stay whole.
    send_lock = asyncio.Lock()

    async def send(payload: dict) -> None:
        async with send_lock:
            await ws.send(json.dumps(payload))

    try:
        async for raw in ws:
            frame = json.loads(raw)
            if not isinstance(frame, dict):
                continue

            kind = frame.get("type")
            if kind == "cancel":
                # The client that asked for this generation is gone. Stop burning GPU on it.
                task = streams.get(frame.get("request_id"))
                if task is not None and not task.done():
                    task.cancel()
                continue
            if kind != "request":
                continue  # pong, or anything the relay doesn't promise — nothing to do

            request_id = frame.get("request_id")

            if frame.get("stream"):

                async def _stream(frame: dict = frame, request_id: object = request_id) -> None:
                    try:
                        reply = await handle_stream_request(frame, config.ollama_url, http, send)
                        await send(reply)
                    except asyncio.CancelledError:
                        # Cancelled by the relay: the coordinator already knows why and has
                        # billed for the chunks it received. Sending a terminal frame now
                        # would be answering a request nobody is listening to.
                        raise
                    finally:
                        streams.pop(request_id, None)

                task = asyncio.create_task(_stream())
                streams[request_id] = task
            else:

                async def _reply(frame: dict = frame) -> None:
                    reply = await handle_request(frame, config.ollama_url, http)
                    await send(reply)

                task = asyncio.create_task(_reply())

            inflight.add(task)
            task.add_done_callback(inflight.discard)

            served += 1
            if stop_after is not None and served >= stop_after:
                if inflight:
                    # let replies reach the relay before we stop; a cancelled stream is an
                    # expected outcome here, not a failure to report
                    await asyncio.gather(*inflight, return_exceptions=True)
                break
    except websockets.ConnectionClosed:
        pass
    finally:
        ping.cancel()
        for task in inflight:
            task.cancel()


async def run(
    config: Config, *, http: httpx.AsyncClient | None = None, stop_after: int | None = None
) -> None:
    """Connect to the relay, authenticate, and serve requests until the tunnel closes.

    ``http`` is injectable so tests can drive a mocked Ollama; ``stop_after`` bounds the loop
    for tests (None = serve forever).
    """
    own_http = http is None
    http = http or httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_SECONDS)
    try:
        async with websockets.connect(config.relay_url, max_size=MAX_FRAME_BYTES) as ws:
            await _authenticate(ws, config)
            await _serve(ws, config, http, stop_after)
    finally:
        if own_http:
            await http.aclose()


def main() -> None:
    """Entry point: load config from the environment and serve forever."""
    asyncio.run(run(load_config()))


if __name__ == "__main__":
    main()
