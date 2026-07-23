#!/usr/bin/env bash
# End-to-end proof that the coordinator stores job blobs in S3 (MinIO): submit a job, let
# it run, then confirm the input and result blobs actually live in the S3 bucket. Run on
# the host from the repo root. Assumes the gridixs3 stack is already up.
set -uo pipefail
API=${GRIDIX_API_URL:-http://127.0.0.1:8080}
COMPOSE="docker compose -p gridixs3 -f smoke/docker-compose.s3.yml"
get() { python3 -c "import sys,json;print(json.load(sys.stdin)['$1'])"; }

echo "== build job image (runs locally on the agent; unrelated to coordinator storage) =="
docker build -q -f smoke/Dockerfile --build-arg SCRIPT=run.py -t gridix-smoke . >/dev/null && echo ok

echo "== register + stake + agent =="
DEV_KEY=$($COMPOSE exec -T -e SMOKE_DEVELOPER_LABEL=s3-dev api python < smoke/register_developer.py | get api_key)
PJ=$($COMPOSE exec -T -e SMOKE_PROVIDER_NAME=s3-prov api python < smoke/onboard_provider.py)
PID=$(echo "$PJ" | get id); PKEY=$(echo "$PJ" | get api_key)
curl -s -XPATCH "$API/providers/me" -H "authorization: Bearer $PKEY" -H 'content-type: application/json' \
  -d '{"cpu_cores":2,"memory_mb":2000,"max_concurrent":2}' >/dev/null
$COMPOSE exec -T -e SEED_PROVIDER_ID="$PID" -e SEED_AMOUNT=200 api python < smoke/seed_stake.py
pkill -f agent-venv 2>/dev/null || true; sleep 1
GRIDIX_API_URL="$API" GRIDIX_PROVIDER_KEY="$PKEY" GRIDIX_POLL_INTERVAL=1 \
  nohup /root/agent-venv/bin/python agent/agent.py </dev/null >/root/agent.log 2>&1 &
sleep 3

echo "== upload input (developer -> coordinator -> S3) =="
printf 'gridix-s3-end-to-end' > /tmp/s3-input
INPUT_REF=$(curl -s -XPOST "$API/blobs" -H "authorization: Bearer $DEV_KEY" \
  -F 'file=@/tmp/s3-input;filename=input' | get ref)
echo "input_ref $INPUT_REF"

echo "== submit job =="
JOB=$(curl -s -XPOST "$API/jobs" -H "authorization: Bearer $DEV_KEY" -H 'content-type: application/json' \
  -d "{\"image_ref\":\"gridix-smoke\",\"input_ref\":\"$INPUT_REF\",\"resource_spec\":{\"cpu_cores\":1,\"memory_mb\":256},\"timeout_seconds\":120}" | get id)
echo "job $JOB"
st=""
for _ in $(seq 1 40); do st=$(curl -s "$API/jobs/$JOB" -H "authorization: Bearer $DEV_KEY" | get status)
  case "$st" in completed|failed|timeout) break;; esac; sleep 2; done
echo "final status: $st"

echo "== result read back (coordinator serves it FROM S3) =="
echo "expected sha256: $(printf 'gridix-s3-end-to-end' | sha256sum | cut -d' ' -f1)"
echo -n "got:            "; curl -s "$API/jobs/$JOB/result" -H "authorization: Bearer $DEV_KEY"; echo

echo "== PROOF: objects actually in the MinIO bucket (queried via the API container) =="
$COMPOSE exec -T api python -c '
import asyncio, os, aioboto3
async def m():
    bucket=os.environ["GRIDIX_S3_BUCKET"]
    s=aioboto3.Session()
    async with s.client("s3", endpoint_url=os.environ["GRIDIX_S3_ENDPOINT_URL"]) as c:
        r=await c.list_objects_v2(Bucket=bucket, Prefix="blobs/")
        objs=r.get("Contents",[])
        print(f"  {len(objs)} object(s) under blobs/ in {bucket}:")
        for o in objs: print("   ", o["Key"], o["Size"], "bytes")
asyncio.run(m())'
pkill -f agent-venv 2>/dev/null || true
