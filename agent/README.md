# GRIDIX provider agent

Rents your machine's CPU/GPU to the GRIDIX network: it polls the coordinator for jobs and
runs each one in a hardened, throwaway Docker container (no network, dropped capabilities,
read-only rootfs, non-root, resource + wall-clock limits — see `build_run_argv`). The image
is assumed hostile; the isolation is the point.

## Requirements

- A Linux host with **Docker** installed and running (the agent shells out to it).
- A **node agent key** from onboarding: sign in with your wallet and call
  `POST /providers/onboard` on the coordinator — it returns the key once.

## Install (recommended)

`install.sh` pulls the published image from GHCR and runs it as a self-restarting
container. The version defaults to the agent's `__version__` (image tag `vX.Y.Z`):

```bash
GRIDIX_API_URL=https://coordinator.example.com \
GRIDIX_PROVIDER_KEY=grdx_your_key \
./install.sh

docker logs -f gridix-agent
```

Re-run to upgrade/reconfigure. Overrides: `GRIDIX_AGENT_VERSION=0.2.0`, or a full ref with
`GRIDIX_AGENT_IMAGE=ghcr.io/gridixcompute/gridix-agent:tag`. Optional passthrough:
`GRIDIX_RELAY_URL` (NAT traversal), `GRIDIX_ENABLE_GPU=true` (pass `--gpus` to job
containers). If the GHCR package is private, `docker login ghcr.io` first.

## Run (manual Docker)

Equivalent to what `install.sh` does, if you prefer to run it yourself:

```bash
docker run -d --restart=always --name gridix-agent \
  -e GRIDIX_API_URL=https://coordinator.example.com \
  -e GRIDIX_PROVIDER_KEY=grdx_your_key \
  -e GRIDIX_AGENT_WORKDIR=/var/lib/gridix-agent \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /var/lib/gridix-agent:/var/lib/gridix-agent \
  ghcr.io/gridixcompute/gridix-agent:v0.1.1
```

Mounting the Docker socket grants host-level control — run the agent only on machines you
own. The job workdir is bind-mounted at the same path inside the container so the input/
output mounts the agent hands the host Docker daemon resolve to real host paths. (If the
coordinator runs on the *same* host, add `--network host` so the agent can reach it.)

## Security: Docker socket access (required for third-party providers)

The raw-socket install above is **only acceptable on a machine you own** — a container
escape from a job would gain full host control. This is a documented, accepted risk for
self-hosting.

**Before any third-party operator runs an agent, the raw socket is FORBIDDEN.** Use the
hardened stack in [`docker-socket-proxy.yml`](docker-socket-proxy.yml): a
`docker-socket-proxy` mounts the socket (read-only) and exposes only the API a job runner
needs — containers, image pulls, the version handshake — while denying `exec` (the classic
escape), build, networks, volumes, swarm, and the rest. The agent talks to it via
`DOCKER_HOST=tcp://docker-socket-proxy:2375` and never mounts the socket itself:

```bash
GRIDIX_API_URL=https://coordinator.example.com \
GRIDIX_PROVIDER_KEY=grdx_your_key \
docker compose -f agent/docker-socket-proxy.yml up -d
```

Verify the restriction on a Docker host with `smoke/verify_socket_proxy.sh` (denied
endpoints → 403, the runner path still works).

## Configuration (env)

| Variable | Default | Purpose |
|----------|---------|---------|
| `GRIDIX_API_URL` | `http://localhost:8000` | Coordinator base URL (must be `https://` to a remote host — the agent refuses cleartext to a non-loopback host so the key isn't leaked on the wire) |
| `GRIDIX_PROVIDER_KEY` | — (required) | Provider API key |
| `GRIDIX_ALLOW_INSECURE_TRANSPORT` | `false` | Escape hatch to permit cleartext `http://`/`ws://` to a remote host on a trusted local network. Leave unset in production — it exposes the provider key. |
| `GRIDIX_ENABLE_GPU` | `false` | Attach GPUs to job containers |
| `GRIDIX_GPU_DEVICES` | — (all visible) | GPU device UUIDs/indices this agent may use, e.g. `GPU-abc,GPU-def` or `0,1` |
| `GRIDIX_RELAY_URL` | — | Relay tunnel for NAT'd providers (poll-only if unset; must be `wss://` to a remote host) |
| `GRIDIX_POLL_INTERVAL` | `1` | Seconds between polls |
| `GRIDIX_HEARTBEAT_INTERVAL` | `15` | Seconds between in-flight heartbeats |
| `GRIDIX_AGENT_WORKDIR` | `/tmp/gridix-agent` | Per-job scratch (input/output) |
| `GRIDIX_CACHE_DIR` / `GRIDIX_CACHE_MAX_BYTES` | `/tmp/gridix-cache` / 20 GiB | Content-addressed artifact cache |

## Multi-GPU boxes

The agent runs one job at a time, so on a box with several GPUs run **one agent per GPU**, each
pinned to a distinct device — that way two jobs never share a card:

```bash
GRIDIX_ENABLE_GPU=true GRIDIX_GPU_DEVICES=GPU-<uuid-0> ... python3 agent.py   # agent 0
GRIDIX_ENABLE_GPU=true GRIDIX_GPU_DEVICES=GPU-<uuid-1> ... python3 agent.py   # agent 1
```

`docker run --gpus device=<ids>` exposes ONLY those GPUs to the container — the job cannot see or
touch the others. Without `GRIDIX_GPU_DEVICES` a GPU job gets all visible GPUs (fine for a single
agent). Note: plain Docker can't hard-cap a container's VRAM (that needs MIG), so the safe model is
one job per card — the coordinator only matches a job to a provider whose VRAM covers the request.

## GPU benchmark (onboarding)

Before a provider can be trusted with GPU jobs, it must submit a **measured** benchmark — the
coordinator scores real numbers, not a self-declared spec. `gpu_benchmark.py` reads the actual
card via `nvidia-smi` (model, VRAM, UUID→hardware fingerprint) and measures throughput by running
a containerized GEMM, then signs and submits the result to `/agent/benchmark`.

```bash
# Build the reference benchmark image once (or supply your own that prints GRIDIX_TFLOPS=<float>).
docker build -t gridix/bench:1 agent/bench

# Measure + submit (run on the provider box, at onboarding).
GRIDIX_COORDINATOR_URL=https://coordinator.example \
GRIDIX_PROVIDER_KEY=<provider key> \
GRIDIX_BENCH_IMAGE=gridix/bench:1 \
GRIDIX_CPU_CORES=8 GRIDIX_MEMORY_MB=32768 \
python3 gpu_benchmark.py
```

The coordinator rejects the provider (disables it) when the measured card contradicts the declared
one — a box declaring an A100 whose `nvidia-smi` shows a T4, a VRAM claim above what's measured, or
a GPU fingerprint already registered by another "node" (one physical card advertised many times).
Without `GRIDIX_BENCH_IMAGE`, identity/VRAM/fingerprint are still measured but throughput reports 0
(never faked) — set the image to prove throughput too.

## Uninstall

```bash
docker rm -f gridix-agent
```
