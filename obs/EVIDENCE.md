# Observability — live verification evidence

Captured on the deploy host (fugazi@100.70.24.39), GRIDIX stack + obs stack running.
This is proof the pipeline works end to end, not that the config "looks right".

## Prometheus targets (both UP)

```
gridix-api up
gridix-scheduler up
```

## Metrics move on real jobs (2 agents, 8 jobs → completed)

Queried live from Prometheus after the jobs completed:

```
gridix_jobs:                    completed = 8
gridix_job_duration_seconds:    p50 = 6.10s   p95 = 7.34s
gridix_ledger_debit_total:      1032
gridix_ledger_credit_total:     1032          (balanced)
gridix_providers_connected:     2
gridix_redis_up / storage_up:   1 / 1
gridix_scheduler_assignments_total: 8         (scheduler target)
```

Grafana renders the same data (dashboard "GRIDIX Overview", uid `gridix-overview`,
datasource `gridix-prom`): a panel query returned `completed = 8` — not an empty panel.

## Alerts actually delivered to the sink

Induced outage: `docker stop gridixs3-redis-1 gridixs3-minio-1`, then restarted. During the
outage `gridix_redis_up` and `gridix_storage_up` read **0** (the scrape still succeeded — a
down dependency is a 0 gauge, not a failed scrape). Alertmanager delivered every notification
to the webhook sink (`docker logs gridixobs-alert-sink-1`):

```
13:57:17 ALERT status=firing   name=StorageUnreachable severity=critical :: Blob storage unreachable
13:57:17 ALERT status=firing   name=RedisUnreachable   severity=critical :: Redis unreachable
13:57:57 ALERT status=resolved name=StorageUnreachable
13:57:57 ALERT status=resolved name=RedisUnreachable
13:58:32 ALERT status=firing   name=StorageUnreachable severity=critical
13:58:32 ALERT status=firing   name=RedisUnreachable   severity=critical
14:00:32 ALERT status=resolved name=StorageUnreachable   ← after redis+minio restarted
14:00:32 ALERT status=resolved name=RedisUnreachable
```

Both `RedisUnreachable` and `StorageUnreachable` fired, were delivered, and resolved.

### Note: the 13:57:57 flap (fixed)

The alert briefly resolved then re-fired while the dependency was still down. Cause: with
Redis down, the `/metrics` health probes blocked long enough for some scrapes to approach the
scrape timeout, so the series went momentarily stale (resolve), then returned to 0 (re-fire).
Fixed by bounding the probes with a short `asyncio.wait_for` timeout so `/metrics` always
returns fast during an outage — no stale-scrape flapping. Verified after the fix: with Redis
stopped, three consecutive `/metrics` scrapes returned in 0.37s / 0.23s / 0.24s with
`gridix_redis_up=0` — fast and correct, well under the scrape timeout.
