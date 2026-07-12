# GRIDIX Backup & Disaster Recovery

The ledger is the source of truth for money, so DR's success criterion is **zero ledger
discrepancy and no orphan records** after restore (verified automatically), not just "the
database is up".

## Objectives (measured, not aspirational)

| Metric | Target | Measured | How |
|---|---|---|---|
| **RPO** (max data loss) | ≤ 1 h | **1 h** | Hourly encrypted `pg_dump` (cron; systemd timer where root is available). Worst case = time since the last successful dump. |
| **RTO** (restore + verify) | ≤ 30 min | **~17.5 s** | Latest drill (`ops/DR_EVIDENCE.md`): restore ~11.7 s + integrity verify ~5.8 s, then a few seconds to bring api/scheduler up on the restored DB. Tooling startup dominates at this data size; `pg_restore` grows with DB size — re-measure at scale. |

Sub-hour RPO needs continuous WAL archiving / PITR (see *Future*). The implemented mechanism
today is scheduled logical backups. **Proven end to end** — backup fires unattended (cron),
restore into an empty DB matches the pre-backup baseline (counts, balanced ledger, zero
orphans), and the restored DB runs as a live system: a new job submitted against it completes
and the ledger stays balanced. Full log: `ops/DR_EVIDENCE.md`.

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

### Last drill result (coordinator DB: 12 jobs [10 completed / 1 failed / 1 timeout], 82 ledger rows, 2 providers)

| Phase | Time |
|---|---|
| Backup (dump + encrypt + upload) | ~12 s (mc container spin-up dominates) |
| Restore (download + decrypt + pg_restore) | ~11.7 s |
| Verify (integrity + counts) | ~5.8 s |

Result: counts match baseline exactly, `discrepancies: 0`, all four orphan checks `0` →
**RESTORE VERIFY: PASS**. Then api+scheduler brought up against the restored DB and a **new job
completed with the ledger still balanced** (debit==credit 1041.67 → 1545.67). Backup object
confirmed encrypted (`Salted__` header). Full evidence: `ops/DR_EVIDENCE.md`. Re-run the drill
after any schema migration or significant data growth and update the numbers above.

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
