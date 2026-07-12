# GRIDIX Backup & Disaster Recovery

The ledger is the source of truth for money, so DR's success criterion is **zero ledger
discrepancy and no orphan records** after restore (verified automatically), not just "the
database is up".

## Objectives (measured, not aspirational)

| Metric | Target | Measured | How |
|---|---|---|---|
| **RPO** (max data loss) | ≤ 1 h | **1 h** | Hourly encrypted `pg_dump` (systemd timer). Worst case = time since the last successful dump. |
| **RTO** (restore + verify) | ≤ 30 min | **~2.6 s** mechanical | Measured on the live coordinator DB (see drill below). Scales with DB size + adds detection/provisioning/repoint time in a real incident. |

Sub-hour RPO needs continuous WAL archiving / PITR (see *Future*). The implemented mechanism
today is scheduled logical backups.

## Implemented backup (real, scheduled)

- **What**: `pg_dump -Fc` (custom, compressed) of the coordinator DB.
- **Encrypted at rest**: `openssl enc -aes-256-cbc -pbkdf2` with a root-only key file — the
  stored object begins with `Salted__`, never plaintext `PGDMP`.
- **Where**: uploaded to S3 / S3-compatible (MinIO) under `s3://<bucket>/backups/`.
- **Retention**: objects older than `GRIDIX_BACKUP_RETENTION_DAYS` (default 7) are pruned each run.
- **Schedule**: `ops/gridix-backup.timer` (`OnCalendar=hourly`, `Persistent=true`) runs
  `ops/gridix-backup.service` → `ops/backup.sh`. Config in `/etc/gridix-backup.env`
  (see `ops/backup.env.example`).

Install:

```bash
sudo cp -r ops /opt/gridix/ops
sudo openssl rand -base64 48 > /etc/gridix-backup.key && sudo chmod 600 /etc/gridix-backup.key
sudo cp ops/backup.env.example /etc/gridix-backup.env   # then edit
sudo cp ops/gridix-backup.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now gridix-backup.timer
systemctl list-timers gridix-backup.timer     # confirm scheduled
```

## Tested restore (real, end-to-end)

`ops/restore.sh` downloads the latest backup, decrypts it, and `pg_restore`s into an empty
scratch DB; `ops/verify_restore.py` then asserts the DR invariants. This is a genuine
restore drill, not a dry run.

```bash
sudo -E bash ops/restore.sh                    # -> gridix_restore (empty), then pg_restore
docker run --rm --network <net> \
  -e GRIDIX_DATABASE_URL=postgresql+asyncpg://gridix:gridix@postgres:5432/gridix_restore \
  -v "$PWD/ops/verify_restore.py:/verify.py" --entrypoint python <control-plane-image> /verify.py
```

`verify_restore.py` checks, and exits non-zero on any failure:
1. **Ledger balances** — `verify_ledger_integrity` returns `[]` (every double-entry group has
   debits == credits).
2. **No orphans** — zero `job_attempts`/`ledger_entries` pointing at a missing job, zero jobs
   pointing at a missing developer.

### Last drill result (coordinator DB: 4 jobs, 22 ledger rows, 40 KiB dump)

| Phase | Time |
|---|---|
| Backup (dump + encrypt + upload) | ~1.4 s |
| Restore (download + decrypt + pg_restore) | ~1.3 s |
| Verify (ledger + orphans) | ~1.3 s |

Result: `ledger discrepancies: 0`, all orphan checks `0` → **RESTORE VERIFY: PASS**.
Backup object confirmed encrypted (`Salted__` header). Re-run the drill after any schema
migration or significant data growth and update the numbers above.

## Redis

Redis holds the job queue (rebuildable) and rate-limit counters (ephemeral), so it is not the
source of truth. Enable **AOF persistence** (`appendfsync everysec`) and a **replica** for
fast failover. On total Redis loss no job is lost: the reaper requeues any `assigned`/
`running` job whose lease lapses, and queued jobs are re-enqueued from the DB (Session 12.5).

## Runbook: Postgres primary loss

1. Provision a fresh Postgres (empty).
2. `ops/restore.sh` (latest backup) → then `ops/verify_restore.py` — must print `PASS`.
3. Point api/scheduler/relay at the restored DB; roll the deployment.
4. Confirm `/health` == 200 and `/metrics` shows the queue draining.
5. Post-incident: compare actual RPO/RTO against the targets above; file a follow-up if missed.

## Future

Continuous WAL archiving + PITR (base backup + `recovery_target_time`) for sub-hour RPO; a
scheduled restore-drill timer that runs `restore.sh` + `verify_restore.py` into a scratch DB
and alerts on failure.
