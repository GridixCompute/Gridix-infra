#!/usr/bin/env bash
# Scheduled, encrypted Postgres backup -> S3/MinIO, with retention. Exits non-zero on any
# failure so the systemd timer surfaces it. Config via env (see ops/backup.env.example).
set -euo pipefail

: "${GRIDIX_BACKUP_KEY_FILE:?path to the AES passphrase file (backup encrypted at rest)}"
: "${GRIDIX_S3_BUCKET:?backup bucket name}"
: "${AWS_ACCESS_KEY_ID:?}"
: "${AWS_SECRET_ACCESS_KEY:?}"
ENDPOINT=${GRIDIX_S3_ENDPOINT_URL:-https://s3.amazonaws.com}
RETENTION_DAYS=${GRIDIX_BACKUP_RETENTION_DAYS:-7}
PGDATABASE=${PGDATABASE:-gridix}
PGUSER=${PGUSER:-gridix}
PG_CONTAINER=${GRIDIX_BACKUP_PG_CONTAINER:-}   # if set, dump via `docker exec` (version-safe)
MC_NET=${GRIDIX_BACKUP_DOCKER_NETWORK:-}       # docker network so mc can reach an in-net MinIO
TS=$(date -u +%Y%m%dT%H%M%SZ)
OBJECT="backups/gridix-${TS}.dump.enc"

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

echo "[backup] pg_dump ${PGDATABASE} @ ${TS}"
if [ -n "$PG_CONTAINER" ]; then
  docker exec -e PGPASSWORD="${PGPASSWORD:-}" "$PG_CONTAINER" \
    pg_dump -Fc -U "$PGUSER" -d "$PGDATABASE" > "$tmp/db.dump"
else
  pg_dump -Fc -U "$PGUSER" -d "$PGDATABASE" > "$tmp/db.dump"
fi

echo "[backup] encrypt at rest (AES-256, PBKDF2)"
openssl enc -aes-256-cbc -pbkdf2 -salt \
  -in "$tmp/db.dump" -out "$tmp/db.dump.enc" -pass "file:$GRIDIX_BACKUP_KEY_FILE"

# mc, containerized so the host needs no extra tooling. MC_HOST_s3 carries creds inline.
scheme="${ENDPOINT%%://*}"; hostpart="${ENDPOINT#*://}"
MC_HOST="${scheme}://${AWS_ACCESS_KEY_ID}:${AWS_SECRET_ACCESS_KEY}@${hostpart}"
mc() { docker run --rm ${MC_NET:+--network "$MC_NET"} -e "MC_HOST_s3=$MC_HOST" \
  -v "$tmp:/w" minio/mc "$@"; }

echo "[backup] upload s3://${GRIDIX_S3_BUCKET}/${OBJECT}"
mc mb --ignore-existing "s3/${GRIDIX_S3_BUCKET}" >/dev/null
mc cp "/w/db.dump.enc" "s3/${GRIDIX_S3_BUCKET}/${OBJECT}"

echo "[backup] prune backups older than ${RETENTION_DAYS}d"
mc rm --recursive --force --older-than "${RETENTION_DAYS}d" "s3/${GRIDIX_S3_BUCKET}/backups/" || true

echo "[backup] done: ${OBJECT}"
