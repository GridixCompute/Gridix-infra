#!/usr/bin/env bash
# GRIDIX provider agent installer — bare-metal, systemd-managed, idempotent.
#
#   sudo GRIDIX_API_URL=https://coordinator.example.com \
#        GRIDIX_PROVIDER_KEY=grdx_... \
#        ./install.sh
#
# Installs the agent into a self-contained venv, writes a root-only env file, and runs it
# as a systemd service that restarts on failure and survives reboots. Re-running upgrades
# the code and deps in place. Optional passthrough env: GRIDIX_RELAY_URL, GRIDIX_ENABLE_GPU.
set -euo pipefail

PREFIX=${GRIDIX_AGENT_PREFIX:-/opt/gridix-agent}
ENV_FILE=${GRIDIX_AGENT_ENV:-/etc/gridix-agent.env}
UNIT=/etc/systemd/system/gridix-agent.service
SRC=$(cd "$(dirname "$0")" && pwd)

: "${GRIDIX_API_URL:?set GRIDIX_API_URL (the coordinator URL)}"
: "${GRIDIX_PROVIDER_KEY:?set GRIDIX_PROVIDER_KEY (from provider registration)}"
[ "$(id -u)" -eq 0 ] || { echo "run as root (systemd + docker access)"; exit 1; }
command -v docker  >/dev/null || { echo "docker is required — the agent runs job containers"; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }

echo "==> installing agent into $PREFIX"
install -d "$PREFIX"
install -m 0644 "$SRC/agent.py" "$PREFIX/agent.py"
install -m 0644 "$SRC/requirements.txt" "$PREFIX/requirements.txt"

echo "==> creating venv + installing deps"
[ -d "$PREFIX/venv" ] || python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --quiet --upgrade pip
"$PREFIX/venv/bin/pip" install --quiet -r "$PREFIX/requirements.txt"

echo "==> writing $ENV_FILE (root-only)"
umask 077
{
  echo "GRIDIX_API_URL=$GRIDIX_API_URL"
  echo "GRIDIX_PROVIDER_KEY=$GRIDIX_PROVIDER_KEY"
  [ -n "${GRIDIX_RELAY_URL:-}" ]  && echo "GRIDIX_RELAY_URL=$GRIDIX_RELAY_URL"
  [ -n "${GRIDIX_ENABLE_GPU:-}" ] && echo "GRIDIX_ENABLE_GPU=$GRIDIX_ENABLE_GPU"
} > "$ENV_FILE"

echo "==> installing systemd unit"
sed -e "s#@PREFIX@#$PREFIX#g" -e "s#@ENV_FILE@#$ENV_FILE#g" \
  "$SRC/gridix-agent.service" > "$UNIT"
systemctl daemon-reload
systemctl enable --now gridix-agent

echo "==> done. Check: systemctl status gridix-agent  |  journalctl -u gridix-agent -f"
