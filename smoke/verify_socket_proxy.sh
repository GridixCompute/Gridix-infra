#!/usr/bin/env bash
# Runtime proof for security wave 2.1 — RUN ON A DOCKER HOST (no Docker in CI/sandbox).
#
# Brings up the socket-proxy and asserts it denies the Docker API surface a job must never
# reach (exec START — the command-execution escape — plus networks, volumes, build, info)
# while the runner path (version handshake + container run via DOCKER_HOST) still works.
#
#   ./smoke/verify_socket_proxy.sh
#
# NOTE on exec: the proxy denies POST /exec/{id}/start (403), which is what actually RUNS a
# command inside a container — the real escape. It does allow POST /containers/{id}/exec
# (create) through the CONTAINERS section (it reaches the daemon → 400 on an empty body),
# but a created exec is inert: without the blocked start, no command ever runs.
set -euo pipefail

COMPOSE="agent/docker-socket-proxy.yml"
# The compose file also defines the agent (with required env). We only start the proxy,
# but compose still parses the whole file, so give the agent vars harmless placeholders.
export GRIDIX_API_URL="${GRIDIX_API_URL:-http://localhost:8000}"
export GRIDIX_PROVIDER_KEY="${GRIDIX_PROVIDER_KEY:-placeholder-not-used}"

docker compose -f "$COMPOSE" up -d docker-socket-proxy
trap 'docker compose -f "$COMPOSE" down' EXIT

# A throwaway client on the proxy's network.
CID="$(docker compose -f "$COMPOSE" ps -q docker-socket-proxy)"
NET="$(docker inspect "$CID" -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}')"
run_curl() { docker run --rm --network "$NET" curlimages/curl:latest -s -o /dev/null -w '%{http_code}' "$@"; }
PROXY="http://docker-socket-proxy:2375"

echo "==> allowed: version handshake + container/image listing (the runner needs these)"
for ep in "/version" "/containers/json" "/images/json"; do
  code="$(run_curl "$PROXY$ep")"
  [ "$code" = "200" ] || { echo "FAIL: $ep returned $code, expected 200 (allowed)"; exit 1; }
  echo "    $ep -> $code (allowed)"
done

echo "==> DENIED (403): exec start, networks, volumes, build, info, secrets"
POST_DENY=("/exec/x/start" "/build")
GET_DENY=("/networks" "/volumes" "/info" "/secrets")
for ep in "${POST_DENY[@]}"; do
  code="$(run_curl -X POST "$PROXY$ep")"
  [ "$code" = "403" ] || { echo "FAIL: POST $ep returned $code, expected 403 (denied)"; exit 1; }
  echo "    POST $ep -> $code (denied)"
done
for ep in "${GET_DENY[@]}"; do
  code="$(run_curl "$PROXY$ep")"
  [ "$code" = "403" ] || { echo "FAIL: GET $ep returned $code, expected 403 (denied)"; exit 1; }
  echo "    GET  $ep -> $code (denied)"
done

echo "==> allowed: a job container runs through the proxy (the runner path)"
# The Docker CLI needs a tcp:// endpoint, not http://.
if docker run --rm --network "$NET" -e DOCKER_HOST="tcp://docker-socket-proxy:2375" \
     docker:cli run --rm hello-world >/dev/null 2>&1; then
  echo "    hello-world ran via the proxy"
else
  echo "FAIL: could not run a container through the proxy"; exit 1
fi

echo "PASS: socket proxy denies the exec-start escape + networks/volumes/build/info; the runner path works."
