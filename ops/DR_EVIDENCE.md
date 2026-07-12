# DR — live restore drill evidence

Captured on fugazi@100.70.24.39 (5.7 GB + swap) against the S3-backed stack. A backup that is
never restored is just a file; this is the restore, proven end to end, including the system
continuing to run from the restored state.

## 0. Baseline (real data, varied state)

Seeded via 2 agents + 12 jobs (10 normal, 1 sleeper→timeout, 1 bad-image→failed):

```
jobs by status:    completed=10  failed=1  timeout=1   (12 total)
providers:         2
ledger_entries:    82
reputation_events: 13
ledger:            debit == credit == 1041.66666666
```

## 1. Automatic backup — cron trigger PROVEN

`pg_dump -Fc` → `openssl enc -aes-256-cbc` (encrypt at rest) → S3/MinIO, retention 7d with
pruning. Scheduled via cron (fugazi is non-root, so a user crontab, not a system timer).
Proof it actually fires (temporarily set to every minute, then restored to hourly):

```
[2026-07-12 15:56:34] gridix-20260712T155627Z.dump.enc   (manual)
[2026-07-12 15:58:07] gridix-20260712T155801Z.dump.enc   (cron)
[2026-07-12 15:59:06] gridix-20260712T155901Z.dump.enc   (cron)
```

Distinct timestamps from unattended cron runs → the schedule triggers. Objects are encrypted
(`Salted__` header, not `PGDMP`). Production schedule: hourly (`0 * * * *`).

## 2/3. Restore to an empty DB + integrity vs baseline

`ops/restore.sh` (one command) downloads the latest backup, decrypts, and pg_restores into a
fresh `gridix_restore`. `ops/verify_restore.py` then gates:

```
counts: jobs=12 providers=2 ledger_entries=82 reputation_events=13
jobs by status: completed=10 failed=1 timeout=1
ledger: debit=1041.66666666 credit=1041.66666666 discrepancies=0
orphans[attempts_without_job]: 0
orphans[jobs_without_developer]: 0
orphans[ledger_without_job]: 0
orphans[terminal_jobs_without_attempt]: 0
RESTORE VERIFY: PASS
```

Every count matches the baseline; ledger balances; zero orphans (no job without an attempt,
no attempt without a job).

## 3c. The restored DB is a working system, not just data

Brought api + scheduler up against `gridix_restore` (port 8081, isolated redis DB), ran an
agent, and submitted a NEW job:

```
ledger BEFORE: debit=credit=1041.66666666  jobs=12
new job → completed, result == sha256(input)
ledger AFTER:  debit=credit=1545.66666666  jobs=13   balanced=YES
```

The system continues from the restored state: a new job completes normally and the ledger
stays balanced. Both invariants hold — ledger correctness, no job lost.

## 4. Measured RPO / RTO

| Metric | Measured | Notes |
|---|---|---|
| **Backup** | ~12 s | Dominated by the `minio/mc` container spin-up; the 43 KB dump + encrypt is sub-second. |
| **Restore (data)** | ~11.7 s | mc download container + `pg_restore`. |
| **Verify** | ~5.8 s | integrity gate (app container start + queries). |
| **RTO (restore + verify)** | **~17.5 s** | + a few seconds to bring api/scheduler up on the restored DB for full service failover. |
| **RPO** | **1 h** | = the backup interval (hourly pg_dump). Worst case = time since the last dump. |

Numbers are small because the dataset is small and tooling startup dominates; `pg_restore`
time grows with DB size — re-measure at production scale. Sub-hour RPO needs WAL archiving/PITR
(future work, noted in docs/DR.md).
