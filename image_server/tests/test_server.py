"""Behaviour tests for the image server — no GPU, no torch, no real diffusers.

The renderer is injected as a fake (the way node/tests mock Ollama), so these run on a CPU
CI. If the server imported torch at module scope this collection would fail on CI where torch
is absent — so a green run here is itself the proof that the ML stack stays lazy.
"""

import base64

from fastapi.testclient import TestClient
from gridix_image_server.server import create_app

# Not a real PNG — the server does not parse it, it only base64-encodes whatever the renderer
# returns. Distinct bytes are enough to prove the round-trip is faithful.
FAKE_PNG = b"\x89PNG\r\n\x1a\n-fake-image-bytes-\x00\x01\x02"


def _client(render=lambda prompt: FAKE_PNG) -> TestClient:
    return TestClient(create_app(render=render))


def test_generate_returns_base64_of_the_rendered_bytes() -> None:
    seen = {}

    def render(prompt: str) -> bytes:
        seen["prompt"] = prompt
        return FAKE_PNG

    res = _client(render).post("/generate", json={"prompt": "a red bicycle on a beach"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert base64.b64decode(body["image_b64"]) == FAKE_PNG  # exact bytes, faithfully encoded
    assert body["bytes"] == len(FAKE_PNG)
    assert seen["prompt"] == "a red bicycle on a beach"  # the prompt reached the renderer


def test_generate_requires_a_prompt() -> None:
    res = _client().post("/generate", json={})
    assert res.status_code == 422  # pydantic rejects the missing field


def test_healthz_is_ok() -> None:
    assert _client().get("/healthz").json() == {"ok": True}
