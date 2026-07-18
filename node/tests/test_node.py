"""Behaviour tests for the thin node — no GPU, no real Ollama, no real relay.

M4 proved this node serves real inference end to end, but it lived only as a script on a
now-dead pod. These tests are what keep the reconstructed package faithful to the relay
contract (api/app/relay.py) and the Ollama backend: a mock relay drives one chat request over
a real local WebSocket, and Ollama is a mocked httpx transport.
"""

import asyncio
import json

import httpx
import pytest
import websockets
from gridix_node.client import Config, handle_request, run

# ── Ollama mock: an httpx transport that returns the OpenAI-compatible shape ──────────────


def _ollama_ok(seen: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            },
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ── Full flow: mock relay WebSocket server drives one chat request ────────────────────────


async def test_full_flow_auth_dispatch_reply() -> None:
    captured: dict = {}
    done = asyncio.Event()

    async def relay(ws, *_):
        captured["auth"] = json.loads(await ws.recv())
        await ws.send(json.dumps({"type": "auth_ok", "provider_id": "prov-123"}))
        await ws.send(
            json.dumps(
                {
                    "type": "request",
                    "request_id": "req-1",
                    "job_id": None,
                    "method": "chat.completions",
                    "payload": {
                        "model": "llama-3.1-8b",
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 40,
                    },
                }
            )
        )
        captured["reply"] = json.loads(await ws.recv())
        done.set()
        await ws.close()

    ollama_seen: dict = {}
    async with (
        websockets.serve(relay, "localhost", 0) as server,
        _ollama_ok(ollama_seen) as http,
    ):
        port = server.sockets[0].getsockname()[1]
        config = Config(
            relay_url=f"ws://localhost:{port}",
            node_key="grdx_test_key",
            ollama_url="http://ollama.test/v1/chat/completions",
        )
        await run(config, http=http, stop_after=1)
        await asyncio.wait_for(done.wait(), timeout=5)

    # Auth advertises the catalogue id the node serves.
    assert captured["auth"] == {
        "type": "auth",
        "key": "grdx_test_key",
        "models": ["llama-3.1-8b"],
    }
    # The node mapped the catalogue id to the Ollama tag before calling the backend.
    assert ollama_seen["body"]["model"] == "llama3.1:8b"
    assert ollama_seen["body"]["messages"] == [{"role": "user", "content": "hi"}]
    # The reply is exactly the frame relay.py/inference.py expect.
    assert captured["reply"] == {
        "type": "response",
        "request_id": "req-1",
        "status": 200,
        "payload": {"content": "hi", "usage": {"prompt_tokens": 5, "completion_tokens": 3}},
    }


# ── handle_request units: mapping, error status, unknown model, unsupported method ─────────


def _request(method: str, model: str) -> dict:
    return {
        "type": "request",
        "request_id": "r-42",
        "method": method,
        "payload": {"model": model, "messages": [{"role": "user", "content": "hi"}]},
    }


async def test_maps_catalogue_id_to_ollama_tag_and_shapes_reply() -> None:
    seen: dict = {}
    async with _ollama_ok(seen) as http:
        reply = await handle_request(
            _request("chat.completions", "llama-3.1-8b"), "http://ollama.test/x", http
        )
    assert seen["body"]["model"] == "llama3.1:8b"  # mapped, not the catalogue id
    assert reply["type"] == "response"
    assert reply["request_id"] == "r-42"  # echoed
    assert reply["status"] == 200
    assert reply["payload"] == {
        "content": "hi",
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }


async def test_ollama_error_becomes_error_status_without_crashing() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as http:
        reply = await handle_request(
            _request("chat.completions", "llama-3.1-8b"), "http://ollama.test/x", http
        )
    assert reply["request_id"] == "r-42"
    assert reply["status"] == 502  # >= 400 → coordinator raises DispatchError, charges nothing
    assert "error" in reply["payload"]


async def test_unknown_model_is_refused_not_silently_served() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200))
    ) as http:
        reply = await handle_request(
            _request("chat.completions", "some-unmapped-model"), "http://ollama.test/x", http
        )
    assert reply["status"] == 400
    assert "some-unmapped-model" in reply["payload"]["error"]


async def test_non_chat_method_is_refused() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200))
    ) as http:
        reply = await handle_request(
            _request("images.generations", "sdxl-turbo"), "http://ollama.test/x", http
        )
    assert reply["status"] == 501
    assert "chat only" in reply["payload"]["error"]


# Guard: pytest is configured with asyncio_mode=auto (repo pyproject), so these run directly.
_ = pytest  # keep the import meaningful if the auto mode ever changes
