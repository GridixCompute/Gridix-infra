---
name: performance-optimization
description: Optimizes performance on both fronts of the eonedge stack — Solana compute-unit budget, account sizing, and transaction cost on-chain/backend, and Core Web Vitals for the Astro/Next frontend. Use when a performance requirement or budget exists, when a transaction hits the compute-unit ceiling or costs too much, when queries or services are slow, or when LCP/INP/CLS or load times need improvement. Use when profiling reveals a bottleneck. Do NOT use to guess — measure first.
---

# Performance Optimization

## Overview

Measure before optimizing. Performance work without measurement is guessing — and guessing adds complexity without improving what matters. Profile first, find the actual bottleneck, fix it, measure again. This skill spans two fronts that are measured with different tools: **on-chain/backend** (Solana compute units, account rent, transaction size and count, query latency) and **frontend** (Core Web Vitals for Astro/Next). On-chain the ceiling is hard — an instruction that exceeds the compute-unit limit doesn't get slow, it *fails* — so the budget is a correctness constraint, not just a nicety. **Optimize only what measurements prove matters.**

## When to Use

- A transaction is failing on compute-unit exhaustion or costs more CU/lamports than budgeted
- Account rent or transaction size is larger than it needs to be
- A performance requirement exists (CU budget, response SLA, load-time budget)
- Users or monitoring report slow behavior
- Core Web Vitals are below thresholds
- You suspect a change introduced a regression
- Building features over large datasets, high traffic, or many accounts

**When NOT to use:** don't optimize before you have evidence. Premature optimization costs more than it gains. Don't reach here to *diagnose a failure happening now* (use `debugging-and-error-recovery`) or to *add the telemetry that measures production* (use `observability-and-instrumentation`).

## The Optimization Workflow

```
1. MEASURE  → Establish a baseline with real data (CU logs / query timings / RUM)
2. IDENTIFY → Find the actual bottleneck, not the assumed one
3. FIX      → Address that specific bottleneck
4. VERIFY   → Measure again; confirm the improvement is real
5. GUARD    → Add a test/budget/monitor so it can't silently regress
```

Skipping step 1 is the cardinal sin. "It's obviously the X" is not a measurement.

---

# Front 1 — On-Chain & Backend

## Targets & budgets (Solana)

| Constraint | Limit / target | Why it matters |
|---|---|---|
| Compute units per instruction | 200k default, 1.4M hard cap (raise via `ComputeBudget`) | Exceeding it = transaction **fails**, not slows |
| Transaction size | 1232 bytes | More accounts/data = fewer instructions per tx |
| Account size | Pay rent-exempt lamports for every byte | Oversized accounts cost real money at scale |
| Backend API (server Rust/TS/Python) | < 200ms p95 | User-facing latency budget |

## Step 1: Measure

**Compute units** — the primary on-chain signal. The runtime logs consumption per instruction; read it, don't guess:

```bash
# solana-test-validator logs show: "consumed 84123 of 200000 compute units"
solana logs | grep -i "consumed"
```

```rust
// In tests, assert the budget so a regression fails CI, not mainnet.
// `anchor test` against a local solana-test-validator; inspect CU in the logs.
// Bump the ceiling explicitly only when justified:
let ix = ComputeBudgetInstruction::set_compute_unit_limit(300_000);
```

**Backend query/latency** — time the real path through the project logger, never `println!`/`print()`:

```rust
// Rust: tracing spans, not ad-hoc timing prints
let _span = tracing::info_span!("db_query", table = "tasks").entered();
let rows = sqlx::query_as!(Task, "SELECT ...").fetch_all(&pool).await?;
// span duration is captured by the tracing subscriber
```

```python
# Python: loguru + a timing context, never print()
from loguru import logger
import time
start = time.perf_counter()
rows = await fetch_tasks()
logger.info("fetched tasks", count=len(rows), ms=(time.perf_counter() - start) * 1000)
```

## Step 2: Identify the bottleneck

| Symptom | Likely cause | Investigation |
|---|---|---|
| Instruction fails / near CU cap | Loops over client-supplied vecs, redundant hashing/deserialization, excessive CPI | Read per-instruction CU logs; bisect by commenting sections |
| Transaction too large | Too many accounts, oversized instruction data | Count accounts; move data into a PDA read on-chain |
| High rent / storage cost | Over-allocated account space, unbounded vecs in state | Compute exact byte layout; cap collection lengths |
| Slow API responses | N+1 queries, missing indexes, unbatched RPC calls | Query log; check indexes; batch `getMultipleAccounts` |
| Memory growth | Unbounded caches, leaked references | Heap/allocator profiling |
| CPU spikes | Synchronous heavy work on the async runtime | Don't block Tokio; offload; profile |

## Step 3: Fix common anti-patterns

**Compute-unit waste (on-chain)** — the loop is where CU goes:

```rust
// BAD: unbounded work over client-controlled input — CU scales with attacker input
for pubkey in ctx.remaining_accounts { /* deserialize + hash each */ }

// GOOD: cap the count, do the minimum work, avoid re-deserializing in a loop
require!(ctx.remaining_accounts.len() <= MAX_BATCH, Err::BatchTooLarge);
```

**Right-size accounts** — you pay rent for every byte:

```rust
// BAD: guess-and-pad
#[account(init, payer = user, space = 1024)]

// GOOD: compute the exact layout (8 discriminator + fields), cap variable parts
#[account(init, payer = user, space = 8 + Vault::INIT_SPACE)] // derive INIT_SPACE
```

**Batch RPC reads (backend)** — one round trip, not N:

```typescript
// BAD: N round trips
for (const pk of pubkeys) await connection.getAccountInfo(pk);
// GOOD: one batched call, typed
const infos = await connection.getMultipleAccountsInfo(pubkeys);
```

**N+1 queries (backend DB):**

```rust
// BAD: one query per row.  GOOD: a single join / IN query.
let tasks = sqlx::query_as!(TaskWithOwner,
    "SELECT t.*, u.name FROM tasks t JOIN users u ON u.id = t.owner_id").fetch_all(&pool).await?;
```

**Unbounded fetching** — always paginate list endpoints (`LIMIT`/`take` + `OFFSET`/cursor).

**Caching** — cache frequently-read, rarely-changed data (config, account metadata) with a TTL; set `Cache-Control` on static/API responses that can tolerate it.

Backend rules in full: `fullstack-standard` → `references/backend-standards.md`.

---

# Front 2 — Frontend (Astro / Next)

## Core Web Vitals targets

| Metric | Good | Needs work | Poor |
|--------|------|-----------|------|
| **LCP** (Largest Contentful Paint) | ≤ 2.5s | ≤ 4.0s | > 4.0s |
| **INP** (Interaction to Next Paint) | ≤ 200ms | ≤ 500ms | > 500ms |
| **CLS** (Cumulative Layout Shift) | ≤ 0.1 | ≤ 0.25 | > 0.25 |

The house default is **static-first, least-JS** — most CWV problems are avoided by *not shipping the JavaScript in the first place* (Astro static, Next server components by default; `"use client"` only where interaction demands it).

## Step 1: Measure

- **Synthetic** (Lighthouse in DevTools or `pnpm dlx @lhci/cli autorun` in CI): reproducible, best for regression gates.
- **RUM** (`web-vitals` in real user sessions): validates a fix actually helped real users.

```typescript
import { onLCP, onINP, onCLS } from 'web-vitals';
onLCP(report); onINP(report); onCLS(report); // report -> your project logger, not console.log
```

## Step 2: Identify — where to start

```
What is slow?
├── First paint (LCP)
│   ├── Large/late hero image? --> responsive <picture>, fetchpriority, correct format
│   ├── Slow TTFB? --> profile the backend (Front 1), check caching/edge
│   └── Render-blocking CSS/JS? --> ship less; static-render; defer non-critical
├── Interaction (INP)
│   └── Too much client JS on the main thread? --> move work server-side; drop the island
├── Layout shift (CLS)
│   └── Images/embeds/fonts without reserved space? --> width/height, font-display
└── Initial load weight
    └── Bundle growing? --> code-split heavy islands, lazy-load rarely-used features
```

## Step 3: Fix common anti-patterns

**Ship less JavaScript first.** An Astro page that renders to static HTML has no INP problem. Reach for an interactive island (or `"use client"`) only when the interaction requires it — that single decision beats most micro-optimizations.

**Images — reserve space, right format, prioritize the LCP element:**

```html
<!-- LCP hero: sized (no CLS), modern format, high priority -->
<img src="/hero.avif" width="1200" height="600" fetchpriority="high" alt="…" />
<!-- Below the fold: lazy + async decode -->
<img src="/content.avif" width="800" height="400" loading="lazy" decoding="async" alt="…" />
```
Always set `width`/`height` (or aspect-ratio) so nothing reflows — that's CLS handled at the source.

**Code-split the heavy, rarely-used island** (Next example):

```tsx
const Chart = dynamic(() => import('./Chart'), { loading: () => <Spinner /> });
```

**Fonts:** `font-display: swap`, preload the one critical face, subset it — late fonts cause both CLS and LCP delay.

Frontend rules in full: `fullstack-standard` → `references/frontend-standards.md`.

---

## Performance Budget

Set budgets and enforce them in CI so regressions fail the build, not production:

```
On-chain:  instruction CU  < budgeted ceiling (assert in anchor test)
           account size     = exact computed layout (no padding)
           tx size          < 1232 bytes
Backend:   API p95          < 200ms
Frontend:  initial JS       < 200KB gzipped
           Lighthouse perf  ≥ 90
           LCP / INP / CLS   within "Good"
```

```bash
# On-chain: CU asserted inside the test suite
anchor test           # fail if an instruction exceeds its CU budget
# Frontend: Lighthouse CI
pnpm dlx @lhci/cli autorun
```

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "We'll optimize later" | Perf debt compounds. Fix obvious anti-patterns now; defer micro-tuning. |
| "It's fast on my machine / on localnet" | Your machine isn't the user's, and localnet CU isn't mainnet contention. Measure representatively. |
| "This optimization is obvious" | If you didn't measure, you don't know. Read the CU log / query log first. |
| "The CU limit is high, we're fine" | Attacker-chosen input scales the loop. An unbounded instruction fails at the worst time. |
| "Padding the account space is safer" | You pay rent for every byte forever. Compute the exact layout. |
| "Users won't notice 100ms" | 100ms measurably impacts conversion. They notice. |
| "The framework handles performance" | Frameworks prevent some issues but not N+1 queries, oversized bundles, or CU blowups. |

## Red Flags

- Optimizing (or claiming a win) with no before/after measurement
- An instruction whose CU scales with client-supplied length, with no cap
- Account `space` padded to a round number instead of the computed layout
- N+1 queries or unbatched `getAccountInfo` calls in a loop
- List endpoints without pagination
- Images without `width`/`height`, lazy loading, or modern formats
- A new interactive island / `"use client"` where static would do
- Bundle size growing with no review; no CWV or CU monitoring in production
- `println!`/`console.log`/`print()` used as the timing mechanism (use `tracing`/`loguru`/`web-vitals`)

## Verification

- [ ] Before/after numbers exist and are specific (CU consumed, query ms, LCP/INP/CLS)
- [ ] The actual bottleneck was identified from measurement, not assumed
- [ ] **On-chain:** instruction CU is under budget and asserted in `anchor test`; account size is the exact computed layout; tx fits 1232 bytes
- [ ] **Backend:** no N+1 or unbatched RPC in new data paths; p95 within budget
- [ ] **Frontend:** Core Web Vitals within "Good"; initial JS within budget; no CLS from unsized media
- [ ] A guard exists so the win can't silently regress (CU assertion, budget check, or monitor)
- [ ] Existing tests still pass — the optimization didn't change behavior

Then run the full **Definition of Done** gate: `fullstack-standard` → `references/definition-of-done.md`.

## See Also

- **`fullstack-standard`** — the bar; `references/backend-standards.md` (on-chain/query rules) and `references/frontend-standards.md` (CWV, images, static-first).
- Sibling skills: **`observability-and-instrumentation`** (the telemetry you measure production with — RED metrics, CU/latency histograms), **`debugging-and-error-recovery`** (a failure happening now, not a measured slowness), **`security-and-hardening`** (unbounded loops over client input are both a CU and a DoS bug).
