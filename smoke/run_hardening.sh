#!/usr/bin/env bash
# Verify the isolation claims at runtime: egress is blocked, the container is hardened,
# and a job that overruns its budget is killed (and removed). Run on the host, repo root.
set -uo pipefail

API=${GRIDIX_API_URL:-http://127.0.0.1:8080}
COMPOSE="docker compose -f smoke/docker-compose.smoke.yml"
get() { python3 -c "import sys,json;print(json.load(sys.stdin)['$1'])"; }
submit() { curl -s -XPOST "$API/jobs" -H "authorization: Bearer $DEV_KEY" -H 'content-type: application/json' \
  -d "{\"image_ref\":\"$1\",\"resource_spec\":{\"cpu_cores\":1,\"memory_mb\":256},\"timeout_seconds\":$2}" | get id; }
poll() { local id=$1 st=""; for _ in $(seq 1 40); do
    st=$(curl -s "$API/jobs/$id" -H "authorization: Bearer $DEV_KEY" | get status)
    case "$st" in completed|failed|timeout) break;; esac; sleep 2; done; echo "$st"; }

echo "== build probe images =="
docker build -q -f smoke/Dockerfile --build-arg SCRIPT=netprobe.py -t gridix-smoke-netprobe . >/dev/null
docker build -q -f smoke/Dockerfile --build-arg SCRIPT=sleeper.py  -t gridix-smoke-sleeper  . >/dev/null
echo ok

echo "== provider + agent =="
DEV_KEY=$(curl -s -XPOST "$API/developers" -H 'content-type: application/json' -d '{"name":"hard-dev"}' | get api_key)
PJ=$($COMPOSE exec -T -e SMOKE_PROVIDER_NAME=hard-prov api python < smoke/onboard_provider.py)
PROV_ID=$(echo "$PJ" | get id); PROV_KEY=$(echo "$PJ" | get api_key)
curl -s -XPATCH "$API/providers/me" -H "authorization: Bearer $PROV_KEY" -H 'content-type: application/json' \
  -d '{"cpu_cores":2,"memory_mb":2000,"max_concurrent":2}' >/dev/null
$COMPOSE exec -T -e SEED_PROVIDER_ID="$PROV_ID" -e SEED_AMOUNT=200 api python < smoke/seed_stake.py
pkill -f agent/agent.py 2>/dev/null || true; sleep 1
GRIDIX_API_URL="$API" GRIDIX_PROVIDER_KEY="$PROV_KEY" GRIDIX_POLL_INTERVAL=1 \
  nohup /root/agent-venv/bin/python agent/agent.py </dev/null > /root/agent.log 2>&1 &
sleep 3

echo "== TEST 1: egress isolation (--network none) =="
EJOB=$(submit gridix-smoke-netprobe 60)
echo "  status: $(poll "$EJOB")"
echo -n "  probe verdict (expect BLOCKED): "; curl -s "$API/jobs/$EJOB/result" -H "authorization: Bearer $DEV_KEY"; echo

echo "== TEST 2: hardening inspect + timeout kill =="
SJOB=$(submit gridix-smoke-sleeper 25)
cid=""; for _ in $(seq 1 20); do cid=$(docker ps --filter "name=gridix-" -q | head -1); [ -n "$cid" ] && break; sleep 1; done
if [ -n "$cid" ]; then
  echo "  live container hardening:"
  docker inspect "$cid" --format '{{json .HostConfig}}' | python3 -c '
import sys,json; h=json.load(sys.stdin)
for k in ["NetworkMode","ReadonlyRootfs","CapDrop","Memory","NanoCpus","PidsLimit"]:
    print(f"    {k} = {h.get(k)}")'
  echo "    User = $(docker inspect "$cid" --format '{{.Config.User}}')"
else
  echo "  (container not caught live)"
fi
echo "  status (expect timeout/failed): $(poll "$SJOB")"
echo "  leftover gridix-* containers (expect 0): $(docker ps -a --filter name=gridix- --format '{{.Names}}' | grep -c . || true)"
