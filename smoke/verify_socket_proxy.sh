#!/usr/bin/env bash
# Runtime proof for security wave 2.1 — RUN ON A DOCKER HOST (no Docker in CI/sandbox).
#
# Brings up the socket-proxy + agent stack and asserts the proxy denies the Docker API
# surface a job must never reach (exec, networks, volumes, build) while the runner path
# (version handshake + container run via DOCKER_HOST) still works.
#
#   GRIDIX_API_URL=... GRIDIX_PROVIDER_KEY=... ./smoke/verify_socket_proxy.sh
set -euo pipefail

COMPOSE="agent/docker-socket-proxy.yml"
docker compose -f "$COMPOSE" up -d docker-socket-proxy
trap 'docker compose -f "$COMPOSE" down' EXIT

# A throwaway client on the proxy's network.
NET="$(docker compose -f "$COMPOSE" ps -q docker-socket-proxy | xargs -I{} docker inspect -f '{{range $k,$_ := .NetworkSettings.Networks}}{{$k}}{{end}}' {})"
run_curl() { docker run --rm --network "$NET" curlimages/curl:latest -s -o /dev/null -w '%{http_code}' "$@"; }
PROXY="http://docker-socket-proxy:2375"

echo "==> allowed: version handshake"
[ "$(run_curl "$PROXY/version")" = "200" ] || { echo "FAIL: /version should be 200"; exit 1; }

echo "==> DENIED: exec, networks, volumes, build, info"
for ep in "/containers/x/exec" "/networks" "/volumes" "/build" "/info"; do
  code="$(run_curl -X POST "$PROXY$ep")"
  # docker-socket-proxy returns 403 for denied sections.
  [ "$code" = "403" ] || { echo "FAIL: $ep returned $code, expected 403 (denied)"; exit 1; }
  echo "    $ep -> $code (denied)"
done

echo "==> allowed: a job container runs through the proxy"
docker run --rm --network "$NET" -e DOCKER_HOST="$PROXY" docker:cli run --rm hello-world >/dev/null \
  && echo "    hello-world ran via proxy"

echo "PASS: socket proxy denies escape endpoints; the runner path works."
