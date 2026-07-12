# GRIDIX provider agent

Rents your machine's CPU/GPU to the GRIDIX network: it polls the coordinator for jobs and
runs each one in a hardened, throwaway Docker container (no network, dropped capabilities,
read-only rootfs, non-root, resource + wall-clock limits — see `build_run_argv`). The image
is assumed hostile; the isolation is the point.

## Requirements

- A Linux host with **Docker** installed and running (the agent shells out to it).
- **Python 3.11+** (bare-metal install) — or just Docker (container install).
- A **provider key** from registration: `POST /providers` on the coordinator returns it once.

## Install (bare-metal, systemd)

Runs the agent as a service that restarts on failure and survives reboots:

```bash
sudo GRIDIX_API_URL=https://coordinator.example.com \
     GRIDIX_PROVIDER_KEY=grdx_your_key \
     ./install.sh

systemctl status gridix-agent
journalctl -u gridix-agent -f
```

Re-run `install.sh` to upgrade in place. Optional env: `GRIDIX_RELAY_URL` (NAT traversal),
`GRIDIX_ENABLE_GPU=true` (pass `--gpus` to job containers).

## Run (Docker)

```bash
docker build -t gridix-agent .
docker run -d --restart=always --name gridix-agent \
  -e GRIDIX_API_URL=https://coordinator.example.com \
  -e GRIDIX_PROVIDER_KEY=grdx_your_key \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gridix-agent
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
sudo systemctl disable --now gridix-agent
sudo rm /etc/systemd/system/gridix-agent.service /etc/gridix-agent.env
sudo rm -rf /opt/gridix-agent
sudo systemctl daemon-reload
```
