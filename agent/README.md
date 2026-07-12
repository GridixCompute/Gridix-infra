# GRIDIX provider agent

Rents your machine's CPU/GPU to the GRIDIX network: it polls the coordinator for jobs and
runs each one in a hardened, throwaway Docker container (no network, dropped capabilities,
read-only rootfs, non-root, resource + wall-clock limits — see `build_run_argv`). The image
is assumed hostile; the isolation is the point.

## Requirements

- A Linux host with **Docker** installed and running (the agent shells out to it).
- A **provider key** from registration: `POST /providers` on the coordinator returns it once.

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
  -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/gridixcompute/gridix-agent:v0.1.0
```

Mounting the Docker socket grants host-level control — run the agent only on machines you
own.

## Configuration (env)

| Variable | Default | Purpose |
|----------|---------|---------|
| `GRIDIX_API_URL` | `http://localhost:8000` | Coordinator base URL |
| `GRIDIX_PROVIDER_KEY` | — (required) | Provider API key |
| `GRIDIX_ENABLE_GPU` | `false` | Pass `--gpus all` to job containers |
| `GRIDIX_RELAY_URL` | — | Relay tunnel for NAT'd providers (poll-only if unset) |
| `GRIDIX_POLL_INTERVAL` | `1` | Seconds between polls |
| `GRIDIX_HEARTBEAT_INTERVAL` | `15` | Seconds between in-flight heartbeats |
| `GRIDIX_AGENT_WORKDIR` | `/tmp/gridix-agent` | Per-job scratch (input/output) |
| `GRIDIX_CACHE_DIR` / `GRIDIX_CACHE_MAX_BYTES` | `/tmp/gridix-cache` / 20 GiB | Content-addressed artifact cache |

## Uninstall

```bash
docker rm -f gridix-agent
```
