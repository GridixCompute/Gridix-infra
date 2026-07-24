"""SDXL-turbo text-to-image server, exposed over HTTP for a node to call.

The node dispatches an ``images.generations`` request here and gets back the PNG **inline
as base64** — by-value transport. That is deliberate: a node has no credential to upload to
the coordinator's blob store, so instead it returns the bytes and lets the coordinator (which
does hold the store) persist them and mint a reachable URL. 512x512 keeps a PNG's base64
under the relay's 1 MiB frame cap, which is what makes by-value viable (see the node bridge
and ``api/app/image_artifacts.py``).

Import-safe on a CPU box: torch/diffusers/Pillow are imported only inside the renderer
loader, so importing this module — and collecting its tests — needs neither a GPU nor the ML
stack. Tests inject a fake renderer; production loads SDXL-turbo via the ``--factory`` entry
point (``uvicorn gridix_image_server.server:create_app --factory``).
"""

from __future__ import annotations

import base64
import io
import os
from collections.abc import Callable

from fastapi import FastAPI
from pydantic import BaseModel

# 512x512: a PNG at this size is ~0.4 MiB, ~0.5 MiB base64 — under the relay's 1 MiB frame
# cap. Larger images would blow the cap and the node would have to refuse them.
IMAGE_SIZE = 512
# SDXL-turbo is a distilled model: 1-4 steps, no classifier-free guidance. Low + fast.
NUM_INFERENCE_STEPS = int(os.environ.get("GRIDIX_SDXL_STEPS", "3"))

# A renderer turns a prompt into PNG bytes. The real one loads SDXL-turbo; tests inject a fake.
Renderer = Callable[[str], bytes]


class GenerateRequest(BaseModel):
    prompt: str


def _default_renderer() -> Renderer:
    """Load SDXL-turbo once and return a ``prompt -> PNG bytes`` renderer.

    torch/diffusers/Pillow are imported HERE, not at module top, so a CPU CI can import this
    module and run the mocked tests without any of them installed.
    """
    import torch
    from diffusers import AutoPipelineForText2Image

    try:
        pipe = AutoPipelineForText2Image.from_pretrained(
            "stabilityai/sdxl-turbo", torch_dtype=torch.float16, variant="fp16"
        ).to("cuda")
    except Exception:  # noqa: BLE001 - the fp16 variant may be absent; fall back to default weights
        pipe = AutoPipelineForText2Image.from_pretrained(
            "stabilityai/sdxl-turbo", torch_dtype=torch.float16
        ).to("cuda")

    def render(prompt: str) -> bytes:
        image = pipe(
            prompt=prompt,
            num_inference_steps=NUM_INFERENCE_STEPS,
            guidance_scale=0.0,
            height=IMAGE_SIZE,
            width=IMAGE_SIZE,
        ).images[0]
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    return render


def create_app(render: Renderer | None = None) -> FastAPI:
    """Build the app. Pass ``render`` to inject a fake (tests); omit to load SDXL-turbo (prod).

    Loading is eager when ``render`` is None, so the process fails fast if the GPU/model is
    missing rather than 500ing on the first request. Because loading happens in ``create_app``
    and not at import, tests that pass a fake never touch torch.
    """
    render = render or _default_renderer()
    app = FastAPI(title="GRIDIX image server")

    @app.post("/generate")
    def generate(req: GenerateRequest) -> dict:
        png = render(req.prompt)
        return {"image_b64": base64.b64encode(png).decode("ascii"), "bytes": len(png)}

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    return app
