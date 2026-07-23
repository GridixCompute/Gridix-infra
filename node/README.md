# GRIDIX inference node (thin, Ollama-backed)

A thin provider node: it holds one outbound WebSocket to the GRIDIX relay and, for each
dispatched chat request, calls a **local Ollama** server and returns the result. No GPU code,
no model weights, no `transformers`/`torch` — that is a vLLM concern; this node only speaks
HTTP to Ollama.

This package is a **reconstruction** of the node proven end to end during the M4 bring-up
(developer → coordinator → relay → node → Ollama → back). It is written from the relay
contract in the code (`api/app/relay.py`, `api/app/dispatch.py`), not from memory, so it may
not be byte-identical to the original pod script — the tests in `tests/` are what pin the
behaviour. If the original script is ever recovered, reconcile against these tests.

## Relay contract this implements

Taken verbatim from `api/app/relay.py` (JSON text frames over one WebSocket to
`/relay/agent`):

| Step | Direction | Frame |
|------|-----------|-------|
| auth (first frame, ≤10 s) | node → relay | `{"type":"auth","key":"grdx_...","models":["llama-3.1-8b"]}` |
| auth ok | relay → node | `{"type":"auth_ok","provider_id":"..."}` |
| auth failed | relay → node | `{"type":"auth_error","reason":"..."}` then close |
| keepalive | node → relay / relay → node | `{"type":"ping"}` / `{"type":"pong"}` |
| dispatch | relay → node | `{"type":"request","request_id","job_id","method","payload"}` |
| reply | node → relay | `{"type":"response","request_id":<echoed>,"status":200,"payload":{"content":"...","usage":{"prompt_tokens":N,"completion_tokens":M}}}` |

- **Method**: only `chat.completions` is served. `images.generations` (Ollama cannot generate
  images) and any other method get a `status` ≥ 400 reply — never a crashed loop.
- **Idle timeout**: the relay closes a silent tunnel after `max(30, heartbeat×3)` s
  (`relay._idle_timeout`); the node pings every ~10 s to stay connected, and each ping also
  refreshes the node's presence so the coordinator keeps selecting it.
- **Frame cap**: 1 MiB per frame (`relay._MAX_FRAME_BYTES`); the client mirrors it.
- **status ≥ 400**: `api/app/dispatch.py` turns any `status ≥ 400` into a `DispatchError`, so
  the coordinator charges the developer nothing for a request the node could not serve.

## Model mapping

The node advertises **catalogue ids** (what the coordinator dispatches, `api/app/catalog.py`)
and maps each to the Ollama tag it actually runs. Start point in `gridix_node/client.py`:

```python
MODEL_MAP = {"llama-3.1-8b": "llama3.1:8b"}
```

Every key is sent in the auth `models` list, so the coordinator only ever routes ids the node
can map. A dispatched id that is not in the map is refused (`status 400`), not served silently.
Extend the map to teach the node more chat models.

## Ollama setup

The node needs an Ollama server serving the mapped tag on `OLLAMA_URL`.

```bash
# 1. Install Ollama (Linux):
curl -fsSL https://ollama.com/install.sh | sh          # or download the release tarball

# 2. Keep models on PERSISTENT storage, not an ephemeral container overlay:
export OLLAMA_MODELS=/workspace/ollama                 # a large, persistent path

# 3. (Optional) allow concurrent requests. Ollama defaults to OLLAMA_NUM_PARALLEL=1, which
#    serialises requests — one slow completion blocks the rest. Raise it if you have VRAM
#    headroom (each parallel slot needs its own KV-cache context):
export OLLAMA_NUM_PARALLEL=4

# 4. Start the server (OpenAI-compatible API on :11434) and pull the chat model:
ollama serve &
ollama pull llama3.1:8b
```

Ollama's `/v1/chat/completions` returns `usage` with `prompt_tokens`/`completion_tokens`,
which the node forwards — the coordinator bills on them.

## Configuration (environment only)

| Variable | Required | Meaning |
|----------|----------|---------|
| `GRIDIX_RELAY_URL` | yes | ws URL of the relay, e.g. `ws://coordinator-host:8100/relay/agent` |
| `GRIDIX_NODE_KEY` | yes | the provider API key (`grdx_...`) issued for this node |
| `OLLAMA_URL` | no | Ollama chat endpoint (default `http://127.0.0.1:11434/v1/chat/completions`) |

## Run

```bash
pip install -r requirements.txt
GRIDIX_RELAY_URL=ws://localhost:8100/relay/agent \
GRIDIX_NODE_KEY=grdx_... \
python -m gridix_node.client
```

## Coordinator prerequisite (no HTTP route — must be seeded)

Before the node can receive work, its provider must exist at the coordinator with:

- a provider row and its node agent key (`grdx_...`), issued once by
  `POST /providers/onboard` from a signed-in wallet session;
- **stake ≥ `min_provider_stake` (default 100)** — `dispatch.py` refuses under-staked
  providers, and there is **no HTTP route to fund stake**. Seed it directly against the
  coordinator's database (see `smoke/seed_stake.py`), or the coordinator will answer
  `503 "no node serving …"` even with the tunnel up.

## Tests

Pure behaviour tests — no GPU, no real Ollama, no real relay (mock relay over a local
WebSocket, Ollama as a mocked httpx transport):

```bash
pip install -r requirements.txt pytest
pytest tests           # or, from the repo root: pytest node/tests
```
