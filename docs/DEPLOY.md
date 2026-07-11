# GRIDIX Deployment — Zero-Downtime Rollout (Session 12.3)

## Rolling deploy

Each app (api, scheduler, relay) deploys as a rolling update: new replicas start, pass
`/health` (or `/relay/health`), take traffic, then old replicas drain. The scheduler and
relay are horizontally scalable (concurrency-safe assignment, per-provider tunnels), so
replicas overlap safely. Rollback = redeploy the previous image tag; because migrations
are expand-only (below), old and new code both run against the same schema.

## Expand/contract migrations (never lock out running code)

Schema changes follow **expand → migrate code → contract**, never a breaking change in one
step:

1. **Expand** — additive only: add nullable columns, new tables, new indexes. The *old*
   code ignores them; the *new* code can use them. Both versions run against this schema,
   so a rolling deploy (and a rollback) never breaks.
2. **Deploy** the new code that writes/reads the new columns.
3. **Backfill** in batches (online, non-locking) if needed.
4. **Contract** — only after every running replica is on the new code, a *later* release
   drops the old column/constraint.

Every migration in `alembic/versions/` is expand-only in its `upgrade()` (enforced by
`tests/test_session12_migration_safety.py`): they add columns/tables/indexes, never drop
or retype in the forward direction. `downgrade()` reverses them for local/testing.

**Never**, in a single migration that a rolling deploy runs: drop/rename a column still
read by the currently-running code, add a NOT NULL column without a server default, or
retype a column. These lock out or crash the old replicas mid-deploy.

## Backfills

Large backfills run as a separate, batched, idempotent job (bounded batch size, sleep
between batches) so they never hold a long transaction or lock a hot table — see Session
12.4 for the operational runbook.

## Rollback

Because forward migrations are additive, rolling back the *code* to the previous image is
always safe against the current schema. Roll back the schema (a contract migration) only
after the code rollback is complete and stable.
