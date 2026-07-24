# GRIDIX image server

An SDXL-turbo text-to-image backend. A GRIDIX node bridges `images.generations` dispatches to
this server over HTTP, the same way it bridges `chat.completions` to Ollama — image generation
and chat are split across two backends so each gets the stack and the GPU headroom it needs.

## Why it's a separate package

The node package (`node/`) needs only websockets + httpx. Image generation needs torch,
diffusers, and a GPU. Keeping them apart means a node host installs one or the other (or both),
and the CPU CI can test the node and the server without ever installing torch.

## Transport (why the server returns base64)

The server returns the PNG **inline as base64**, not a URL:

```
POST /generate  {"prompt": "..."}  ->  {"image_b64": "<base64 PNG>", "bytes": 391234}
```

A node has no credential to upload to the coordinator's blob store (`POST /blobs` is
developer-gated), so it cannot host a durable URL itself — and a node-hosted URL
(`http://127.0.0.1:8500/...`) is unreachable by a user's browser and dies with the node. So the
node returns the bytes by value, and the **coordinator** stores them and mints a reachable URL.
512x512 keeps the base64 under the relay's 1 MiB frame cap, which is what makes by-value viable.

## Run (GPU host)

```bash
python -m venv venv && . venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cu124   # match your driver
pip install -r requirements.txt
# SDXL-turbo (~7 GB fp16) downloads on first start:
uvicorn gridix_image_server.server:create_app --factory --host 127.0.0.1 --port 8500
```

Point the node at it with `IMAGE_SERVER_URL=http://127.0.0.1:8500/generate`.

## VRAM and coexistence with Ollama

SDXL-turbo (fp16) is resident at ~9 GB. It coexists with the chat node's Ollama model
(`llama3.2:3b`, ~4 GB) on a single 20 GB card — measured ~13.3 GB used, no OOM — which is the
point of the chat/image split: one GPU can serve both. Ollama idle-unloads its model between
requests, so the steady-state footprint is even lower.

## Tests

```bash
pytest image_server/tests -q
```

The renderer is injected as a fake, so the suite runs on CPU with no torch, no diffusers, and
no GPU — the same mocking discipline `node/tests` uses for Ollama.
