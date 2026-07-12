#!/usr/bin/env bash
# Restore an encrypted backup from S3/MinIO into a target Postgres database. Downloads the
# latest backup (or the object given as $1), decrypts, and pg_restore's into the target.
# The target should be an EMPTY database — the DR drill restores into a scratch DB and then
# runs ops/verify_restore.py. Config via env (see ops/backup.env.example).
set -euo pipefail

: "${GRIDIX_BACKUP_KEY_FILE:?}"
: "${GRIDIX_S3_BUCKET:?}"
: "${AWS_ACCESS_KEY_ID:?}"
: "${AWS_SECRET_ACCESS_KEY:?}"
ENDPOINT=${GRIDIX_S3_ENDPOINT_URL:-https://s3.amazonaws.com}
MC_NET=${GRIDIX_BACKUP_DOCKER_NETWORK:-}
RESTORE_DB=${GRIDIX_RESTORE_DB:-gridix_restore}
RESTORE_USER=${GRIDIX_RESTORE_USER:-gridix}
RESTORE_PG_CONTAINER=${GRIDIX_RESTORE_PG_CONTAINER:-}  # if set, pg_restore via docker exec
OBJECT=${1:-}

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

scheme="${ENDPOINT%%://*}"; hostpart="${ENDPOINT#*://}"
MC_HOST="${scheme}://${AWS_ACCESS_KEY_ID}:${AWS_SECRET_ACCESS_KEY}@${hostpart}"
mc() { docker run --rm ${MC_NET:+--network "$MC_NET"} -e "MC_HOST_s3=$MC_HOST" \
  -v "$tmp:/w" minio/mc "$@"; }

if [ -z "$OBJECT" ]; then
  echo "[restore] finding latest backup"
  OBJECT="backups/$(mc ls "s3/${GRIDIX_S3_BUCKET}/backups/" | awk '{print $NF}' | sort | tail -1)"
fi
echo "[restore] object: ${OBJECT}"
mc cp "s3/${GRIDIX_S3_BUCKET}/${OBJECT}" "/w/db.dump.enc"

echo "[restore] decrypt"
openssl enc -d -aes-256-cbc -pbkdf2 \
  -in "$tmp/db.dump.enc" -out "$tmp/db.dump" -pass "file:$GRIDIX_BACKUP_KEY_FILE"

echo "[restore] (re)create empty target db ${RESTORE_DB}"
psql_do() {
  if [ -n "$RESTORE_PG_CONTAINER" ]; then
    docker exec -i -e PGPASSWORD="${PGPASSWORD:-}" "$RESTORE_PG_CONTAINER" psql -U "$RESTORE_USER" -d postgres -v ON_ERROR_STOP=1 -c "$1"
  else
    psql -U "$RESTORE_USER" -d postgres -v ON_ERROR_STOP=1 -c "$1"
  fi
}
psql_do "DROP DATABASE IF EXISTS ${RESTORE_DB};"
psql_do "CREATE DATABASE ${RESTORE_DB} OWNER ${RESTORE_USER};"

echo "[restore] pg_restore -> ${RESTORE_DB}"
if [ -n "$RESTORE_PG_CONTAINER" ]; then
  docker exec -i -e PGPASSWORD="${PGPASSWORD:-}" "$RESTORE_PG_CONTAINER" \
    pg_restore -U "$RESTORE_USER" -d "$RESTORE_DB" --no-owner < "$tmp/db.dump"
else
  pg_restore -U "$RESTORE_USER" -d "$RESTORE_DB" --no-owner "$tmp/db.dump"
fi

echo "[restore] done -> ${RESTORE_DB}"
