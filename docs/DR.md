# GRIDIX Backup & Disaster Recovery (Session 12.4)

## Objectives

| Metric | Target | Rationale |
|---|---|---|
| **RPO** (max data loss) | ≤ 5 min | Continuous WAL archiving; at most the last unarchived segment is lost. |
| **RTO** (max downtime)  | ≤ 30 min | Restore latest base backup + replay WAL to the failure point. |

The ledger is the source of truth for money, so DR's success criterion is **zero ledger
discrepancy** after restore (see verification below), not just "the database is up".

## Postgres

- **Base backups**: nightly `pg_basebackup` (or managed snapshots) retained 30 days.
- **PITR**: continuous WAL archiving to object storage. Restore = latest base backup +
  `recovery_target_time` up to just before the incident.
- **Tested restore**: a scheduled job restores the latest backup into a scratch instance
  and runs the integrity check below; the drill fails loudly if it can't meet RTO or the
  ledger doesn't balance.

## Redis

Redis holds the job queue (rebuildable) and rate-limit counters (ephemeral), so it is not
the source of truth. Still, enable **AOF persistence** (`appendfsync everysec`) and a
**replica** for fast failover. On total Redis loss, queued job ids are re-derived: the
scheduler's reaper requeues any `assigned`/`running` job whose lease lapses, and queued
jobs are re-enqueued from the DB, so no job is lost (Session 12.5).

## Restore verification — zero ledger discrepancy

After any restore, run the ledger integrity check before taking traffic:

```python
from app.ledger import verify_ledger_integrity
discrepancies = await verify_ledger_integrity(session)
assert discrepancies == []   # every transaction group balances (debits == credits)
```

Because the ledger is append-only, double-entry, and every write is a balanced group, a
correct PITR restore lands on a consistent point where the invariant holds. A non-empty
result means the restore stopped mid-transaction — recover to a different `recovery_target`
and re-verify. This is exercised by `tests/test_session12_dr.py`.

## Runbook: Postgres primary failure

1. Promote the streaming replica (or restore latest base backup + WAL to failure time).
2. Run `verify_ledger_integrity` — must return `[]`.
3. Point the api/scheduler/relay at the new primary; roll the deployment.
4. Confirm `/health` == 200 and `/metrics` shows queue draining.
5. Post-incident: verify RPO/RTO against the targets above; file a follow-up if missed.
