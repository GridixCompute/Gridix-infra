"""Behaviour tests for the thin node — no GPU, no real Ollama, no real relay.

M4 proved this node serves real inference end to end, but it lived only as a script on a
now-dead pod. These tests are what keep the reconstructed package faithful to the relay
contract (api/app/relay.py) and the Ollama backend: a mock relay drives one chat request over
a real local WebSocket, and Ollama is a mocked httpx transport.
"""

import asyncio
import contextlib
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
                        "model": "llama3.2-3b",
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

    # Auth advertises every id the node serves. The coordinator routes on this list, so it
    # must contain exactly the models this node's Ollama runs — today just the free tier's.
    assert captured["auth"]["type"] == "auth"
    assert captured["auth"]["key"] == "grdx_test_key"
    assert set(captured["auth"]["models"]) == {"llama3.2-3b"}
    # The node mapped the catalogue id to the Ollama tag before calling the backend.
    assert ollama_seen["body"]["model"] == "llama3.2:3b"
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
            _request("chat.completions", "llama3.2-3b"), "http://ollama.test/x", http
        )
    assert seen["body"]["model"] == "llama3.2:3b"  # mapped, not the catalogue id
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
            _request("chat.completions", "llama3.2-3b"), "http://ollama.test/x", http
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


# ── Streaming: chunk frames, a terminal response, and cancellation ────────────────────────


def _ollama_stream(
    events: list[str],
    *,
    on_request=None,
    hang: asyncio.Event | None = None,
    trailing: list[str] | None = None,
):
    """A mocked Ollama that answers /v1/chat/completions with an SSE stream.

    ``hang`` parks the response after ``events``, which is what a real backend
    mid-generation looks like — the state a cancel has to be able to interrupt. ``trailing``
    is what it would go on to emit once released, so a test can prove a cancelled node
    stopped rather than merely that it was slow.
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        if on_request is not None:
            on_request(json.loads(request.content))

        async def body():
            for event in events:
                yield f"data: {event}\n\n".encode()
                await asyncio.sleep(0)
            if hang is not None:
                await hang.wait()
            for event in trailing or []:
                yield f"data: {event}\n\n".encode()
                await asyncio.sleep(0)

        return httpx.Response(200, content=body(), headers={"content-type": "text/event-stream"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _delta(text: str) -> str:
    return json.dumps({"choices": [{"delta": {"content": text}}]})


async def test_a_streamed_request_emits_chunks_then_a_terminal_response() -> None:
    """The node turns Ollama's stream into chunk frames and one terminal response."""
    sent: list[dict] = []
    seen_body: dict = {}

    async def send(frame: dict) -> None:
        sent.append(frame)

    from gridix_node.client import handle_stream_request

    http = _ollama_stream(
        [_delta("Hel"), _delta("lo"), "[DONE]"],
        on_request=lambda b: seen_body.update(b),
    )
    frame = {
        "type": "request",
        "request_id": "req-s",
        "method": "chat.completions",
        "stream": True,
        "payload": {"model": "llama3.2-3b", "messages": [{"role": "user", "content": "hi"}]},
    }
    async with http:
        terminal = await handle_stream_request(
            frame, "http://ollama/v1/chat/completions", http, send
        )

    # Ollama was asked to stream — buffering the whole reply would defeat the point.
    assert seen_body["stream"] is True

    assert [f["type"] for f in sent] == ["chunk", "chunk"]
    assert [f["delta"] for f in sent] == ["Hel", "lo"]
    # Cumulative, not per-chunk: a coordinator that misses a frame still bills the right total.
    assert [f["tokens"] for f in sent] == [1, 2]
    assert all(f["request_id"] == "req-s" for f in sent)

    assert terminal["type"] == "response"
    assert terminal["status"] == 200
    assert terminal["payload"]["content"] == "Hello"
    assert terminal["payload"]["usage"]["completion_tokens"] == 2


async def test_a_backend_failure_mid_stream_becomes_a_terminal_error_not_a_crash() -> None:
    """The receive loop must survive a broken backend, and say so in a frame.

    After chunks have been sent the HTTP status is long committed, so the only way to
    report a failure is the terminal frame — the coordinator releases the hold on it.
    """
    from gridix_node.client import handle_stream_request

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "model exploded"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    frame = {
        "type": "request",
        "request_id": "req-e",
        "method": "chat.completions",
        "stream": True,
        "payload": {"model": "llama3.2-3b", "messages": []},
    }
    async with http:
        terminal = await handle_stream_request(frame, "http://ollama/v1", http, lambda f: _noop())

    assert terminal["status"] == 502
    assert "error" in terminal["payload"]


async def _noop() -> None:
    return None


async def test_an_unmapped_model_is_refused_before_streaming() -> None:
    from gridix_node.client import handle_stream_request

    sent: list[dict] = []

    async def send(frame: dict) -> None:
        sent.append(frame)

    http = _ollama_stream([_delta("x"), "[DONE]"])
    frame = {
        "type": "request",
        "request_id": "req-u",
        "method": "chat.completions",
        "stream": True,
        "payload": {"model": "not-a-model", "messages": []},
    }
    async with http:
        terminal = await handle_stream_request(frame, "http://ollama/v1", http, send)

    assert terminal["status"] == 400
    assert sent == [], "an unservable model must not emit chunks"


async def test_a_cancel_frame_stops_the_generation() -> None:
    """`cancel` is what stops a GPU working for a client that has gone.

    The assertion has to be that the node produces NOTHING MORE after a cancel, and the
    fake backend is arranged so that an uncancelled node demonstrably would: a second delta
    and a terminal response are waiting behind `released`. A first attempt at this test used
    `stop_after=1`, whose teardown cancels every in-flight task anyway — so it passed with
    the cancel branch deleted, which is to say it tested the teardown, not the feature.
    """
    released = asyncio.Event()
    frames: list[dict] = []
    done = asyncio.Event()

    async def relay(ws, *_):
        json.loads(await ws.recv())  # auth
        await ws.send(json.dumps({"type": "auth_ok", "provider_id": "p"}))
        await ws.send(
            json.dumps(
                {
                    "type": "request",
                    "request_id": "req-c",
                    "method": "chat.completions",
                    "stream": True,
                    "payload": {"model": "llama3.2-3b", "messages": []},
                }
            )
        )
        frames.append(json.loads(await ws.recv()))  # the first chunk
        await ws.send(json.dumps({"type": "cancel", "request_id": "req-c"}))
        await asyncio.sleep(0.05)  # let the node act on the cancel
        released.set()  # a node still attached would now receive "b" and finish

        # Nothing further may arrive. A node that ignored the cancel sends chunk "b" and
        # then its terminal response, and this read returns instead of timing out.
        with contextlib.suppress(TimeoutError):
            frames.append(await asyncio.wait_for(ws.recv(), timeout=0.4))
        done.set()
        await ws.close()

    http = _ollama_stream([_delta("a")], trailing=[_delta("b"), "[DONE]"], hang=released)
    async with websockets.serve(relay, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        config = Config(relay_url=f"ws://127.0.0.1:{port}", node_key="k", ollama_url="http://o/v1")
        async with http:
            with contextlib.suppress(websockets.ConnectionClosed):
                await asyncio.wait_for(run(config, http=http), timeout=5)

    assert frames[0]["type"] == "chunk"
    assert frames[0]["delta"] == "a"
    assert len(frames) == 1, f"the node kept generating after cancel: {frames[1:]}"
