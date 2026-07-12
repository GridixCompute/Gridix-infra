#!/usr/bin/env bash
# GRIDIX provider agent installer — pulls the published image from GHCR and runs it as a
# self-restarting Docker container. Idempotent (re-run to upgrade/reconfigure).
#
#   GRIDIX_API_URL=https://coordinator.example.com \
#   GRIDIX_PROVIDER_KEY=grdx_... \
#   ./install.sh
#
# Version defaults to the agent's __version__ (image tag vX.Y.Z). Override with
# GRIDIX_AGENT_VERSION=0.2.0, or pin a full ref with GRIDIX_AGENT_IMAGE=ghcr.io/...:tag.
# Optional passthrough: GRIDIX_RELAY_URL, GRIDIX_ENABLE_GPU.
set -euo pipefail

SRC=$(cd "$(dirname "$0")" && pwd)
DEFAULT_VERSION=$(grep -oE '__version__ = "[^"]+"' "$SRC/agent.py" 2>/dev/null \
  | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "0.1.0")
VERSION=${GRIDIX_AGENT_VERSION:-$DEFAULT_VERSION}
IMAGE=${GRIDIX_AGENT_IMAGE:-ghcr.io/gridixcompute/gridix-agent:v${VERSION}}
NAME=${GRIDIX_AGENT_NAME:-gridix-agent}
# Job I/O lives here. It is mounted at the SAME path inside the agent container so that the
# bind mounts the agent hands the host Docker daemon (input/output) resolve to real host
# paths — without this, a containerized agent using the host socket mounts nonexistent paths.
WORKDIR=${GRIDIX_AGENT_WORKDIR:-/var/lib/gridix-agent}

: "${GRIDIX_API_URL:?set GRIDIX_API_URL (the coordinator URL)}"
: "${GRIDIX_PROVIDER_KEY:?set GRIDIX_PROVIDER_KEY (from provider registration)}"
command -v docker >/dev/null || { echo "docker is required — the agent runs job containers"; exit 1; }

echo "==> pulling $IMAGE"
docker pull "$IMAGE"

echo "==> (re)starting container '$NAME'"
mkdir -p "$WORKDIR"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --restart=always \
  -e GRIDIX_API_URL="$GRIDIX_API_URL" \
  -e GRIDIX_PROVIDER_KEY="$GRIDIX_PROVIDER_KEY" \
  -e GRIDIX_AGENT_WORKDIR="$WORKDIR" \
  ${GRIDIX_RELAY_URL:+-e GRIDIX_RELAY_URL="$GRIDIX_RELAY_URL"} \
  ${GRIDIX_ENABLE_GPU:+-e GRIDIX_ENABLE_GPU="$GRIDIX_ENABLE_GPU"} \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$WORKDIR:$WORKDIR" \
  "$IMAGE"

echo "==> done ($IMAGE). logs: docker logs -f $NAME"
