#!/usr/bin/env bash
# Non-interactive P0 smoke driver, run ON the Docker host from the repo root.
# Brings a job through queued -> assigned -> running -> completed against the live stack,
# then prints the result, the ledger, and the container's enforced hardening.
set -euo pipefail

API=${GRIDIX_API_URL:-http://127.0.0.1:8080}
COMPOSE="docker compose -f smoke/docker-compose.smoke.yml"
get() { python3 -c "import sys,json;print(json.load(sys.stdin)['$1'])"; }

echo "== build smoke image =="
docker build -q -f smoke/Dockerfile --build-arg SCRIPT=run.py -t gridix-smoke . >/dev/null && echo ok

echo "== register developer + provider =="
DEV_KEY=$(curl -s -XPOST "$API/developers" -H 'content-type: application/json' -d '{"name":"smoke-dev"}' | get api_key)
PROV_JSON=$($COMPOSE exec -T -e SMOKE_PROVIDER_NAME=smoke-prov api python < smoke/onboard_provider.py)
PROV_ID=$(echo "$PROV_JSON" | get id)
PROV_KEY=$(echo "$PROV_JSON" | get api_key)
curl -s -XPATCH "$API/providers/me" -H "authorization: Bearer $PROV_KEY" -H 'content-type: application/json' \
  -d '{"cpu_cores":2,"memory_mb":2000,"max_concurrent":2}' >/dev/null
echo "provider $PROV_ID"

echo "== seed stake =="
$COMPOSE exec -T -e SEED_PROVIDER_ID="$PROV_ID" -e SEED_AMOUNT=200 api python < smoke/seed_stake.py

echo "== upload input =="
printf 'gridix-smoke-input' > /tmp/smoke-input
INPUT_REF=$(curl -s -XPOST "$API/blobs" -H "authorization: Bearer $DEV_KEY" \
  -F 'file=@/tmp/smoke-input;filename=input' | get ref)
echo "input_ref $INPUT_REF"

echo "== start agent (background) =="
[ -d /root/agent-venv ] || python3 -m venv /root/agent-venv
/root/agent-venv/bin/pip install -q httpx loguru
pkill -f agent/agent.py 2>/dev/null || true
GRIDIX_API_URL="$API" GRIDIX_PROVIDER_KEY="$PROV_KEY" GRIDIX_POLL_INTERVAL=1 \
  nohup /root/agent-venv/bin/python agent/agent.py </dev/null > /root/agent.log 2>&1 &
sleep 3

echo "== submit job =="
JOB_ID=$(curl -s -XPOST "$API/jobs" -H "authorization: Bearer $DEV_KEY" -H 'content-type: application/json' \
  -d "{\"image_ref\":\"gridix-smoke\",\"input_ref\":\"$INPUT_REF\",\"resource_spec\":{\"cpu_cores\":1,\"memory_mb\":256},\"timeout_seconds\":120}" | get id)
echo "job $JOB_ID"

echo "== poll for terminal state =="
ST=""
for i in $(seq 1 40); do
  ST=$(curl -s "$API/jobs/$JOB_ID" -H "authorization: Bearer $DEV_KEY" | get status)
  echo "  [$i] $ST"
  case "$ST" in completed|failed|timeout) break;; esac
  sleep 3
done

echo "== result =="
echo "expected sha256: $(printf 'gridix-smoke-input' | sha256sum | cut -d' ' -f1)"
echo -n "got:            "; curl -s "$API/jobs/$JOB_ID/result" -H "authorization: Bearer $DEV_KEY"; echo

echo "== ledger (audit) =="
curl -s "$API/jobs/$JOB_ID/audit" -H "authorization: Bearer $DEV_KEY" | python3 -m json.tool

echo "== agent log tail =="
tail -15 /root/agent.log
echo "== FINAL STATUS: $ST =="
