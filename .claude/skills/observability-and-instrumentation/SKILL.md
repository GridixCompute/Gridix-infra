---
name: observability-and-instrumentation
description: Instruments eonedge code so production behavior is visible and diagnosable across the stack — Rust services with `tracing`, Python with `loguru`, structured logs, RED/USE metrics, and alerting. Use when adding logging, metrics, tracing, or alerts to any Rust/Python/TS service, indexer, or job. Use when shipping any feature that runs in production and you need evidence it works. Use when an incident took too long to diagnose because you couldn't tell what happened. Never reach for `print()`, `println!`, or `console.log` — those are the anti-pattern this skill exists to replace.
---

# Observability and Instrumentation

## Overview

Code you can't observe is code you can't operate. Observability is the ability to answer "what is the system doing and why?" from the outside, using the telemetry the code emits. Instrumentation is not a post-launch add-on — it's written alongside the feature, the same way tests are. If a feature ships without telemetry, the first user-reported bug becomes archaeology instead of a query. This is primarily a **backend** skill — Rust services and indexers use **`tracing`**, Python services use **`loguru`**, and **never `print()` / `println!` / `console.log`**. Logging goes through the project logger, always.

## When to Use

- Building any backend feature that will run in production (service, endpoint, job, indexer, RPC consumer)
- Adding a new external integration, retry loop, queue, or cross-service call
- A production incident took too long to diagnose ("we couldn't tell what happened")
- Setting up or reviewing alerting rules
- Reviewing a PR that adds I/O, retries, queues, or cross-service/RPC calls

**When NOT to use:**
- Diagnosing a failure happening right now → `debugging-and-error-recovery` (observability is what makes that fast next time)
- Profiling and fixing measured slowness → `performance-optimization` (this skill emits the metrics that skill reads)
- Frontend RUM/Web-Vitals reporting → that lives in `performance-optimization`; here we cover the services behind it

## Process

### 1. Define "working" before instrumenting

Telemetry without a question is noise. Before adding anything, write down 2–4 questions an on-call engineer will ask about this feature:

```
FEATURE: settle-payout job (reads on-chain state, writes DB)
QUESTIONS ON-CALL WILL ASK:
1. What fraction of payouts settle on first attempt vs after retry?
2. When a payout fails permanently, why? (RPC timeout? account not found? insufficient funds?)
3. Is the RPC endpoint slower than usual?
→ Every signal below must help answer one of these.
```

If you can't name the questions, you'll log everything and learn nothing.

### 2. Pick the right signal for each question

| Signal | Answers | Cost | Example |
|---|---|---|---|
| **Structured log** | "What happened in this specific case?" | Per-event; grows with traffic | `payout_failed` with the RPC error code |
| **Metric** | "How often / how fast, in aggregate?" | Fixed per series; cheap to query | p99 latency of `getAccountInfo` |
| **Trace** | "Where did time go across hops?" | Per-request; usually sampled | one slow settlement, hop by hop |

Rule of thumb: metrics tell you **that** something is wrong, traces tell you **where**, logs tell you **why**.

### 3. Structured logging

Log events, not prose. Every line is a structured record with a stable event name and machine-readable fields — never string interpolation, and **never `print`/`println!`/`console.log`.**

```rust
// Rust — tracing with structured fields, not format-string prose
// BAD: println!("payout {id} failed for {user} after {n} retries");
tracing::warn!(
    event = "payout_failed",
    payout_id = %id,
    provider = "helius",
    error_code = %err.code(),
    attempt = n,
    "payout failed"
);
```

```python
# Python — loguru with bound structured fields (never print())
from loguru import logger
logger.bind(event="payout_failed", payout_id=id, error_code=err.code, attempt=n) \
      .warning("payout failed")
```

**Log levels — use them consistently:**

| Level | Meaning | On-call action |
|---|---|---|
| `error` | Invariant broken; someone may need to act | Investigate |
| `warn` | Degraded but handled (retry succeeded, fallback used) | Watch for trends |
| `info` | Significant business event (payout settled, job finished) | None |
| `debug`/`trace` | Diagnostic detail | Off in production by default |

**Correlation IDs are mandatory.** Generate or accept a request/job ID at the boundary and attach it to every log line, span, and outbound call — otherwise you can't reconstruct one request from interleaved logs. In Rust, a `tracing` span carries it automatically:

```rust
// Every log emitted inside this span inherits request_id — no manual threading
let span = tracing::info_span!("handle_request", request_id = %req_id);
let _guard = span.enter();
```

**Never log secrets, keypairs, tokens, or full PII.** This is a hard rule from `security-and-hardening` — telemetry pipelines are a classic leak path. Allowlist fields; never log whole request bodies, signed transactions, or private keys. On-chain: a transaction signature is safe to log; a keypair or seed is not.

### 4. Metrics

For request-driven services, instrument **RED** on every endpoint and every external dependency (including each RPC method you call): **R**ate, **E**rrors, **D**uration (a latency **histogram**, not an average). For resources (queues, pools, hosts, indexer lag), use **USE**: **U**tilization, **S**aturation, **E**rrors. The vendor-neutral path is the OpenTelemetry metrics API; a Prometheus exporter is a fine backend — the RED/USE and cardinality rules are identical either way.

```rust
// Latency histogram keyed by BOUNDED labels only
let hist = metrics::histogram!("rpc_request_duration_seconds",
    "method" => "getAccountInfo", "status_class" => "5xx"); // '5xx', not '503'
hist.record(elapsed.as_secs_f64());
```

**Cardinality is the failure mode.** Every unique label combination is a separate time series. Labels come from small fixed sets — route template, status class, RPC method, provider name. Never use user IDs, wallet pubkeys, transaction signatures, raw URLs, or error text as labels; those belong in logs and traces.

```
OK as label:    route="/api/payouts/:id"   status_class="5xx"   rpc_method="getAccountInfo"
NEVER a label:  user_id, wallet_pubkey, tx_signature, request_id, full URL, error message text
```

Track averages never, percentiles always — an average hides the 1% of users having a terrible time. Read p50/p95/p99 off the histogram.

### 5. Distributed tracing

Use OpenTelemetry — it's the vendor-neutral standard and auto-instrumentation covers HTTP and common DB/RPC clients with near-zero code. In Rust, `tracing` + `tracing-opentelemetry` bridges spans to OTLP:

```rust
// Bridge tracing spans to OTLP once at startup; every #[instrument] span exports.
use tracing_subscriber::prelude::*;
tracing_subscriber::registry()
    .with(tracing_opentelemetry::layer().with_tracer(otlp_tracer()?))
    .with(tracing_subscriber::fmt::layer().json()) // structured stdout too
    .init();
```

Add manual spans only around meaningful units of work (`derive_pdas`, `submit_tx`, `confirm_signature`) and attach attributes on-call will filter by. **Propagate context across every async and network boundary** — HTTP headers, queue metadata — or the trace dies at the gap. Sample head-based at a low rate; keep 100% of errors if the backend supports tail sampling.

### 6. Alerting

Alert on **symptoms users feel**, not on causes:

```
SYMPTOM (page-worthy):            CAUSE (dashboard, not a page):
error rate > 1% for 5 min         RPC node CPU at 85%
p99 latency > 2s                  one pod restarted
payout queue age > 10 min         indexer disk at 70%
```

Cause-based alerts fire when nothing is wrong and miss failures you didn't predict. Symptom-based alerts fire exactly when users are hurt. Rules for every alert:

1. **Actionable** — if the response is "ignore it, it self-heals", delete it.
2. **Links to a runbook** — even three lines: what it means, first query to run, escalation path.
3. **Threshold + duration justified** by an SLO or historical data, not a guess.
4. **Two severities only** — *page* (user-facing, act now) and *ticket* (degradation, act this week). A third tier trains people to ignore everything.

### 7. Verify the telemetry itself

Instrumentation is code; it can be wrong. Before calling it done, trigger the paths and read the actual output:

- Force an error in staging → find it in the logs by `request_id`, confirm fields are structured (not `Debug`-dumped prose)
- Send test traffic → confirm metric series appear with expected labels and sane values
- Follow one request across services in the tracing UI → no broken spans
- Fire each new alert once (temporarily lower the threshold) → it reaches the right channel and the runbook link works

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll add logging after it works" | "After" becomes "after the first incident" — the most expensive moment to discover you're blind. Instrument as you build. |
| "`println!` / `print()` / `console.log` is fine for now" | Unstructured output can't be filtered, correlated, or alerted on, and it violates the house rule. `tracing`/`loguru` cost five extra minutes once. |
| "More logs = more observability" | Unstructured noise makes incidents slower. Three queryable events beat three hundred prose lines. |
| "We'll just look at dashboards when it breaks" | Dashboards built without defined questions show everything except the answer. Start from on-call questions. |
| "Alert on everything important, tune later" | A noisy pager trains people to ignore it. The tuning never happens; the missed real page does. |
| "Wallet pubkey as a metric label makes debugging easier" | It also makes the metrics backend fall over. High-cardinality lookups belong in logs and traces. |
| "Tracing is overkill for two services" | Two services already means cross-service latency questions logs can't answer. Auto-instrumentation makes it trivial. |

## Red Flags

- `println!` / `print()` / `console.log` used for anything meant to survive to production
- A feature PR with retries, queues, RPC, or external calls and zero new telemetry
- Log lines built by string interpolation instead of structured fields
- No correlation/request ID — each log line is an orphan
- Metrics labeled with user IDs, wallet pubkeys, tx signatures, raw URLs, or error text (cardinality bomb)
- Latency tracked as an average with no percentiles
- Alerts that fire daily and get acknowledged without action
- Alerts on causes (CPU, memory) paging humans while user-facing error rate is unmonitored
- Secrets, keypairs, tokens, or full request bodies appearing in logs
- "It works on my machine" as the only evidence a production feature is healthy

## Verification

- [ ] The on-call questions for this feature are written down, and each signal maps to one
- [ ] All log output is structured via `tracing`/`loguru` (no `print`/`println!`/`console.log`), with stable event names and a correlation ID on every line
- [ ] No secrets, keypairs, tokens, or unredacted PII in any log line (spot-check real output)
- [ ] RED metrics exist for every new endpoint and every external dependency (incl. each RPC method), with bounded label sets
- [ ] Latency is a histogram; p95/p99 are queryable
- [ ] A single request can be followed end-to-end in the tracing UI without broken spans
- [ ] Every new alert is symptom-based, has a runbook link, and was test-fired once
- [ ] An induced failure in staging was located via telemetry alone, without reading the source

Then run the full **Definition of Done** gate: `fullstack-standard` → `references/definition-of-done.md`.

## See Also

- **`fullstack-standard`** — the bar; `references/backend-standards.md` mandates `loguru` over `print()` and "log through the project logger, not stdout".
- Sibling skills: **`performance-optimization`** (reads the latency/CU histograms this skill emits), **`security-and-hardening`** (the never-log-secrets rule; audit-logging security events), **`debugging-and-error-recovery`** (consumes this telemetry to diagnose a live failure).
