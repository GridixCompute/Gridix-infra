#!/usr/bin/env bash
# Load + chaos drill against the live coordinator. Starts M agents, submits N jobs, injects
# chaos (kill a random agent, bounce Redis, bounce storage) mid-flight, drains, then reports
# throughput/latency and asserts the two invariants (ledger correctness, no job lost).
set -uo pipefail
API=${GRIDIX_API_URL:-http://127.0.0.1:8080}
COMPOSE="docker compose -p gridixs3 -f smoke/docker-compose.s3.yml"
AGENTS=${AGENTS:-3}
JOBS=${JOBS:-24}
JOB_IMG=gridix-smoke-mid
AGENT_IMG=gridix-agent:local
get(){ python3 -c "import sys,json;print(json.load(sys.stdin)[\"$1\"])"; }

echo "== build images =="
docker build -q -f smoke/Dockerfile --build-arg SCRIPT=midwork.py -t "$JOB_IMG" . >/dev/null
docker build -q -t "$AGENT_IMG" ./agent >/dev/null && echo ok

echo "== start $AGENTS agents (containerized, host-net) =="
for i in $(seq 1 "$AGENTS"); do
  PJ=$(curl -s -XPOST "$API/providers" -H 'content-type: application/json' -d "{\"name\":\"chaos-p$i\"}")
  PID=$(echo "$PJ"|get id); PKEY=$(echo "$PJ"|get api_key)
  curl -s -XPATCH "$API/providers/me" -H "authorization: Bearer $PKEY" -H 'content-type: application/json' \
    -d '{"cpu_cores":4,"memory_mb":4000,"max_concurrent":2}' >/dev/null
  $COMPOSE exec -T -e SEED_PROVIDER_ID="$PID" -e SEED_AMOUNT=500 api python < smoke/seed_stake.py >/dev/null
  wd=/var/lib/gridix-agent/a$i; mkdir -p "$wd"
  docker rm -f "chaos-agent-$i" >/dev/null 2>&1 || true
  docker run -d --name "chaos-agent-$i" --restart=always --network host \
    -e GRIDIX_API_URL="$API" -e GRIDIX_PROVIDER_KEY="$PKEY" -e GRIDIX_AGENT_WORKDIR="$wd" \
    -e GRIDIX_POLL_INTERVAL=1 -e GRIDIX_HEARTBEAT_INTERVAL=5 \
    -v /var/run/docker.sock:/var/run/docker.sock -v "$wd:$wd" "$AGENT_IMG" >/dev/null
done
sleep 4

echo "== pre-upload input + register developer =="
DJ=$(curl -s -XPOST "$API/developers" -H 'content-type: application/json' -d '{"name":"chaos-dev"}')
DEV_ID=$(echo "$DJ"|get id); DEV_KEY=$(echo "$DJ"|get api_key)
printf chaos-load-input > /tmp/ci
IREF=$(curl -s -XPOST "$API/blobs" -H "authorization: Bearer $DEV_KEY" -F 'file=@/tmp/ci;filename=input' | get ref)

echo "== submit $JOBS jobs =="
for j in $(seq 1 "$JOBS"); do
  curl -s -XPOST "$API/jobs" -H "authorization: Bearer $DEV_KEY" -H 'content-type: application/json' \
    -d "{\"image_ref\":\"$JOB_IMG\",\"input_ref\":\"$IREF\",\"resource_spec\":{\"cpu_cores\":1,\"memory_mb\":256},\"timeout_seconds\":120}" >/dev/null &
done
wait
echo "submitted"

echo "== CHAOS (background) =="
(
  sleep 6;  echo "[chaos] SIGKILL chaos-agent-$(( (RANDOM % AGENTS) + 1 ))"; docker kill "chaos-agent-$(( (RANDOM % AGENTS) + 1 ))" >/dev/null 2>&1 || true
  sleep 7;  echo "[chaos] bounce Redis";   docker stop gridixs3-redis-1 >/dev/null 2>&1; sleep 3; docker start gridixs3-redis-1 >/dev/null 2>&1
  sleep 7;  echo "[chaos] bounce MinIO";   docker stop gridixs3-minio-1 >/dev/null 2>&1; sleep 3; docker start gridixs3-minio-1 >/dev/null 2>&1
) &
CHAOS=$!

echo "== drain + sample queue depth =="
qdepth(){ docker exec gridixs3-postgres-1 psql -U gridix -d gridix -tAc \
  "select count(*) from jobs where status='queued'" 2>/dev/null | tr -d '[:space:]'; }
term_count(){ curl -s "$API/jobs?limit=200" -H "authorization: Bearer $DEV_KEY" | python3 -c \
  "import sys,json;d=json.load(sys.stdin);print(sum(1 for j in d if j['status'] in ('completed','failed','timeout')))" 2>/dev/null || echo 0; }
maxq=0
deadline=$(( $(date +%s) + 300 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  term=$(term_count); q=$(qdepth); q=${q:-0}
  [ "$q" -gt "$maxq" ] 2>/dev/null && maxq=$q
  echo "  terminal=$term/$JOBS queued=$q"
  [ "$term" -ge "$JOBS" ] 2>/dev/null && break
  sleep 4
done
wait $CHAOS 2>/dev/null || true
echo "max queue depth observed: $maxq"

echo "== REPORT + INVARIANTS =="
docker cp smoke/chaos_report.py gridixs3-api-1:/chaos_report.py
$COMPOSE exec -T -e CHAOS_DEV_ID="$DEV_ID" api python /chaos_report.py
RC=$?

echo "== cleanup agents =="
for i in $(seq 1 "$AGENTS"); do docker rm -f "chaos-agent-$i" >/dev/null 2>&1 || true; done
exit $RC
