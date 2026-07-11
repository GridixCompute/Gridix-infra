# GRIDIX Runbooks, SLOs & Alerts (Session 12.7)

## SLOs

| SLO | Target | Measured by |
|---|---|---|
| Job assignment latency (queued → assigned) | p95 < 10 s | scheduler timing / `gridix_queue_depth` trend |
| API availability (`/health` 200) | 99.9% monthly | uptime probe |
| Settlement correctness | 100% (zero ledger discrepancy) | `verify_ledger_integrity` (12.4) |
| No job silently lost | 100% | every job reaches terminal or is reassigned |

## Alerts

`app.alerts.evaluate_alerts` fires on symptoms (each maps to a runbook below):

| Alert | Severity | Condition |
|---|---|---|
| `ledger_discrepancy` | critical | any unbalanced ledger group (`ledger_discrepancies > 0`) |
| `mass_provider_dropout` | critical | `providers_connected < alert_min_connected_providers` |
| `scheduler_backlog` | warning | `queue_depth > alert_queue_backlog` |

Each is exercised by `tests/test_session12_alerts.py` (fires under the failure condition,
silent when healthy).

## Runbook: scheduler stuck (`scheduler_backlog`)

**Symptom:** queue depth climbing, jobs staying `queued`.
1. Check `/metrics` `gridix_queue_depth` and `gridix_providers_total`; are providers
   connected (`providers_connected`)? If zero → see mass dropout.
2. Check scheduler replica health/logs. Restart a wedged replica (assignment is
   concurrency-safe; multiple replicas are fine).
3. The recovery sweep (12.5) re-enqueues queued jobs each tick — confirm it's running.
4. If providers exist but nothing assigns, check the matcher gates (stake/presence/degraded)
   aren't excluding everyone (`/providers/me`).

## Runbook: mass provider dropout (`mass_provider_dropout`)

**Symptom:** connected provider count collapses.
1. Is it us or them? Check relay/API availability and the network path.
2. The reaper drains in-flight jobs of unreachable providers (7.6) → they requeue; confirm
   no job is stuck.
3. Communicate; scale remaining capacity; providers reconnect via poll/ping and become
   eligible again automatically.

## Runbook: ledger discrepancy (`ledger_discrepancy`)

**Symptom:** `verify_ledger_integrity` returns a non-empty set. This must never happen in
normal operation (every posting is a balanced group).
1. **Freeze settlement** immediately (stop the scheduler's finalize path).
2. Identify the unbalanced `entry_group`(s) from the check output; inspect the surrounding
   transactions and the audit chain (`verify_audit_chain`, 12.6).
3. Most likely a bad restore (12.4) — restore to a clean `recovery_target` and re-verify.
4. Post a *new* balancing correction group (never edit history); document in an incident.
