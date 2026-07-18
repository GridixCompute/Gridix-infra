"""Thin GRIDIX inference node: a relay WebSocket client backed by a local Ollama server.

Reconstructed from the relay contract in ``api/app/relay.py`` + ``api/app/dispatch.py`` and
the M4 end-to-end bring-up (developer → coordinator → relay → this node → Ollama → back).
The wire protocol this implements, taken from ``relay.py`` (not from prose):

  node → relay:  {"type": "auth", "key": "grdx_...", "models": [...]}   first frame, <=10s
  relay → node:  {"type": "auth_ok", "provider_id": "..."}                              (on success)
                 {"type": "auth_error", "reason": "..."}                                (on failure)
  node → relay:  {"type": "ping"}   relay → node: {"type": "pong"}                       (keepalive)
  relay → node:  {"type": "request", "request_id", "job_id", "method", "payload"}
  node → relay:  {"type": "response", "request_id": <echoed>, "status": 200,
                  "payload": {"content": "...", "usage": {"prompt_tokens", "completion_tokens"}}}

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
from dataclasses import dataclass, field

import httpx
import websockets

# Catalogue id (what the coordinator dispatches, see api/app/catalog.py) → Ollama model tag.
# Extend this as the node is taught to serve more chat models; every key here is advertised
# to the relay in the auth frame, so the coordinator only ever routes ids the node can map.
MODEL_MAP: dict[str, str] = {
    "llama-3.1-8b": "llama3.1:8b",
}

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/v1/chat/completions"

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
    models: list[str] = field(default_factory=lambda: list(MODEL_MAP))
    ping_interval: float = PING_INTERVAL_SECONDS


def load_config() -> Config:
    """Build the node config from the environment. Raises KeyError if a required var is unset."""
    return Config(
        relay_url=os.environ["GRIDIX_RELAY_URL"],
        node_key=os.environ["GRIDIX_NODE_KEY"],
        ollama_url=os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL),
        models=list(MODEL_MAP),
    )


def _response(request_id: object, status: int, payload: dict) -> dict:
    """A relay ``response`` frame. ``request_id`` is echoed so the relay correlates the reply."""
    return {"type": "response", "request_id": request_id, "status": status, "payload": payload}


async def _run_chat(payload: dict, ollama_url: str, http: httpx.AsyncClient) -> dict:
    """Serve one chat.completions payload via Ollama; return the coordinator's payload dict.

    The reply payload is exactly what ``inference.py`` reads: ``content`` (choices[0].message)
    and ``usage`` with ``prompt_tokens``/``completion_tokens`` (used to bill the request).
    Raises ``_UnknownModelError`` for an unmapped id and httpx/parse errors for a bad backend;
    the caller turns both into a ``status >= 400`` response.
    """
    catalogue_id = payload.get("model")
    ollama_model = MODEL_MAP.get(catalogue_id) if isinstance(catalogue_id, str) else None
    if ollama_model is None:
        raise _UnknownModelError(catalogue_id)

    body: dict = {"model": ollama_model, "messages": payload.get("messages", [])}
    # Forward the tuning knobs the coordinator passed through, when present.
    for key in ("max_tokens", "temperature", "seed"):
        if payload.get(key) is not None:
            body[key] = payload[key]

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


async def handle_request(frame: dict, ollama_url: str, http: httpx.AsyncClient) -> dict:
    """Turn one relay ``request`` frame into the ``response`` frame to send back.

    Never raises: every failure path becomes a ``status >= 400`` response so the receive loop
    keeps running and the coordinator charges nothing for a request the node could not serve.
    """
    request_id = frame.get("request_id")
    method = frame.get("method")
    payload = frame.get("payload") or {}

    if method != "chat.completions":
        # Ollama serves chat only; the node registers no image models, so the coordinator
        # never routes images.generations here — but refuse it explicitly if one arrives.
        return _response(request_id, 501, {"error": f"method {method!r} not served (chat only)"})

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
    served = 0
    try:
        async for raw in ws:
            frame = json.loads(raw)
            if not isinstance(frame, dict) or frame.get("type") != "request":
                continue  # pong, or anything the relay doesn't promise — nothing to do

            async def _reply(frame: dict = frame) -> None:
                reply = await handle_request(frame, config.ollama_url, http)
                await ws.send(json.dumps(reply))

            task = asyncio.create_task(_reply())
            inflight.add(task)
            task.add_done_callback(inflight.discard)

            served += 1
            if stop_after is not None and served >= stop_after:
                if inflight:
                    await asyncio.gather(*inflight)  # let the reply reach the relay before we stop
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
