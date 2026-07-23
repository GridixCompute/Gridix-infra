#!/usr/bin/env bash
# Launch one sleeper job and inspect the agent-built container's enforced hardening.
set -uo pipefail
API=${GRIDIX_API_URL:-http://127.0.0.1:8080}
get() { python3 -c "import sys,json;print(json.load(sys.stdin)['$1'])"; }

DEV_KEY=$(curl -s -XPOST "$API/developers" -H 'content-type: application/json' -d '{"name":"insp-dev"}' | get api_key)
PJ=$(docker compose -f smoke/docker-compose.smoke.yml exec -T -e SMOKE_PROVIDER_NAME=insp-prov api python < smoke/onboard_provider.py)
PID=$(echo "$PJ" | get id); PKEY=$(echo "$PJ" | get api_key)
curl -s -XPATCH "$API/providers/me" -H "authorization: Bearer $PKEY" -H 'content-type: application/json' \
  -d '{"cpu_cores":2,"memory_mb":2000,"max_concurrent":2}' >/dev/null
docker compose -f smoke/docker-compose.smoke.yml exec -T -e SEED_PROVIDER_ID="$PID" -e SEED_AMOUNT=200 api python < smoke/seed_stake.py >/dev/null
pkill -f agent/agent.py 2>/dev/null || true; sleep 1
GRIDIX_API_URL="$API" GRIDIX_PROVIDER_KEY="$PKEY" GRIDIX_POLL_INTERVAL=1 \
  nohup /root/agent-venv/bin/python agent/agent.py </dev/null >/root/agent.log 2>&1 &
sleep 3

JOB=$(curl -s -XPOST "$API/jobs" -H "authorization: Bearer $DEV_KEY" -H 'content-type: application/json' \
  -d '{"image_ref":"gridix-smoke-sleeper","resource_spec":{"cpu_cores":1,"memory_mb":256},"timeout_seconds":90}' | get id)
echo "sleeper job: $JOB"

cid=""
for _ in $(seq 1 30); do cid=$(docker ps --filter "name=gridix-$JOB" -q); [ -n "$cid" ] && break; sleep 1; done
[ -z "$cid" ] && { echo "container not caught"; exit 1; }

echo "=== HARDENING (agent-launched container) ==="
docker inspect "$cid" --format '{{json .HostConfig}}' | python3 -c '
import sys,json
h=json.load(sys.stdin)
for k in ["NetworkMode","ReadonlyRootfs","CapDrop","Memory","NanoCpus","PidsLimit","SecurityOpt"]:
    print(f"  {k} = {h.get(k)}")'
echo "  User = $(docker inspect "$cid" --format '{{.Config.User}}')"

echo "=== kill early → confirm auto-removed (no leak) ==="
docker kill "$cid" >/dev/null 2>&1; sleep 2
echo "  leftover gridix-* containers = $(docker ps -a --filter name=gridix- --format '{{.Names}}' | grep -c . || true)"
pkill -f agent/agent.py 2>/dev/null || true
