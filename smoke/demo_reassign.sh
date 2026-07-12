#!/usr/bin/env bash
# P0.5 live demo: a node dies mid-job → the coordinator reclaims and reassigns the job,
# which then completes on a fresh attempt. Proves "no job silently lost". Run on the host.
set -uo pipefail
API=${GRIDIX_API_URL:-http://127.0.0.1:8080}
COMPOSE="docker compose -f smoke/docker-compose.smoke.yml"
get() { python3 -c "import sys,json;print(json.load(sys.stdin)['$1'])"; }
info() { curl -s "$API/jobs/$1" -H "authorization: Bearer $DEV_KEY"; }

echo "== build slowwork image =="
docker build -q -f smoke/Dockerfile --build-arg SCRIPT=slowwork.py -t gridix-smoke-slow . >/dev/null && echo ok

echo "== provider + agent =="
DEV_KEY=$(curl -s -XPOST "$API/developers" -H 'content-type: application/json' -d '{"name":"reassign-dev"}' | get api_key)
PJ=$(curl -s -XPOST "$API/providers" -H 'content-type: application/json' -d '{"name":"provA"}')
PID=$(echo "$PJ" | get id); PKEY=$(echo "$PJ" | get api_key)
curl -s -XPATCH "$API/providers/me" -H "authorization: Bearer $PKEY" -H 'content-type: application/json' \
  -d '{"cpu_cores":2,"memory_mb":2000,"max_concurrent":2}' >/dev/null
$COMPOSE exec -T -e SEED_PROVIDER_ID="$PID" -e SEED_AMOUNT=200 api python < smoke/seed_stake.py >/dev/null
start_agent() {
  pkill -f agent-venv 2>/dev/null || true; sleep 1
  GRIDIX_API_URL="$API" GRIDIX_PROVIDER_KEY="$PKEY" GRIDIX_POLL_INTERVAL=1 GRIDIX_HEARTBEAT_INTERVAL=5 \
    nohup /root/agent-venv/bin/python agent/agent.py </dev/null >/root/agent.log 2>&1 &
}
start_agent; sleep 3

echo "== submit slowwork job =="
JOB=$(curl -s -XPOST "$API/jobs" -H "authorization: Bearer $DEV_KEY" -H 'content-type: application/json' \
  -d '{"image_ref":"gridix-smoke-slow","resource_spec":{"cpu_cores":1,"memory_mb":256},"timeout_seconds":200}' | get id)
echo "job $JOB"

echo "== wait until running on the node =="
st=""
for _ in $(seq 1 30); do st=$(info "$JOB" | get status); [ "$st" = running ] && break; sleep 1; done
echo "  status=$st attempt_count=$(info "$JOB" | get attempt_count)"

echo "== SIMULATE NODE DEATH: hard-kill agent (SIGKILL) so it can't report, then its container =="
pkill -9 -f agent-venv 2>/dev/null || true   # SIGKILL: no graceful result submission
docker kill "gridix-$JOB" >/dev/null 2>&1 || true
echo "  agent hard-killed, container killed"

echo "== reaper should reclaim the job off the dead node =="
for i in $(seq 1 20); do
  st=$(info "$JOB" | get status); ac=$(info "$JOB" | get attempt_count)
  echo "  [$i] status=$st attempt_count=$ac"
  [ "$st" = queued ] && { echo "  -> reclaimed (requeued), not lost"; break; }
  case "$st" in completed|failed|timeout) break;; esac
  sleep 3
done

echo "== node comes back: restart agent → job reassigns and completes =="
start_agent
for i in $(seq 1 60); do
  st=$(info "$JOB" | get status); ac=$(info "$JOB" | get attempt_count)
  echo "  [$i] status=$st attempt_count=$ac"
  case "$st" in completed|failed|timeout) break;; esac
  sleep 3
done

echo "== audit =="
curl -s "$API/jobs/$JOB/audit" -H "authorization: Bearer $DEV_KEY" | python3 -c '
import sys,json
a=json.load(sys.stdin)
print("final status:", a["job"]["status"], "| attempt_count:", a["job"]["attempt_count"])
for at in a["attempts"]:
    print("  attempt", at["attempt_number"], "->", at["outcome"], "provider", str(at["provider_id"])[:8])
d=sum(float(e["amount"]) for e in a["ledger"] if e["direction"]=="debit")
c=sum(float(e["amount"]) for e in a["ledger"] if e["direction"]=="credit")
print("ledger: debit=%.6f credit=%.6f balanced=%s" % (d, c, abs(d-c)<1e-6))'
pkill -f agent-venv 2>/dev/null || true
