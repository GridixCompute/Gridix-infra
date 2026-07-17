#!/usr/bin/env bash
# Entrypoint dispatch for the GRIDIX control-plane image.
#   api        → run migrations, then serve the FastAPI app
#   scheduler  → run the scheduler + reaper worker (Session 3)
#   chain      → run the on-chain watcher / settlement / reconcile worker
#   relay      → run the NAT-traversal relay server (Session 7.2)
set -euo pipefail

role="${1:-api}"

wait_for_db() {
  echo "waiting for database migrations..."
  # alembic is idempotent; retry until Postgres accepts connections.
  for _ in $(seq 1 30); do
    if alembic upgrade head; then
      return 0
    fi
    echo "db not ready, retrying in 2s..."
    sleep 2
  done
  echo "database never became ready" >&2
  exit 1
}

case "$role" in
  api)
    wait_for_db
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
  scheduler)
    # The scheduler assumes the api has already applied migrations.
    exec python -m app.scheduler
    ;;
  chain)
    # Settlement engine: watcher + settlement + reconcile. Its own process so the money
    # path doesn't share a lifecycle with job dispatch.
    exec python -m app.chain_worker
    ;;
  relay)
    # Standalone relay for NAT'd providers; shares the DB for key validation.
    # --ws-max-size caps a WebSocket frame at 1 MiB (1048576 bytes). relay.py already
    # states a 1 MiB limit (_MAX_FRAME_BYTES), but that check runs *after* receive_text()
    # has buffered the whole frame, so without this the real ceiling is uvicorn's 16 MiB
    # default and the app cap only bounds parsing, not memory. This makes the server refuse
    # oversized frames at the protocol layer, enforcing the limit the code already declares.
    exec uvicorn app.relay:app --host 0.0.0.0 --port 8100 --ws-max-size 1048576
    ;;
  *)
    echo "unknown role: $role (expected: api | scheduler | chain | relay)" >&2
    exit 2
    ;;
esac
