---
name: shipping-and-launch
description: Prepares safe production launches for the eonedge stack — on-chain programs, servers, and web. Use when deploying to production, promoting a Solana program from devnet to mainnet, cutting a release, migrating account data, or opening a beta. Use when you need a pre-launch checklist tied to the Definition of Done, a staged localnet→devnet→mainnet rollout, monitoring, or a rollback plan. Use before any work on an ephemeral compute node that could be lost on redeploy.
---

# Shipping and Launch

## Overview

Ship with confidence, not hope. The goal is not to deploy — it's to deploy so that
the change is **reversible, observable, and incremental**. On a Solana stack the
stakes are asymmetric: a bad frontend deploy is a rollback; a bad mainnet program
touching real SOL can be unrecoverable. So you earn each step. Clear the Definition
of Done first, promote through localnet → devnet → mainnet, watch the dashboards
you set up *before* launch, and keep a rollback ready you've actually tested. A
launch you can't reverse and can't observe is a gamble, not a release.

## When to Use

- Promoting a program or service to production for the first time.
- Moving an Anchor program from **devnet to mainnet**.
- Cutting a release of a server SDK or web app.
- Migrating on-chain account data or infrastructure.
- Opening a beta / early-access to real users.
- Any deployment that carries risk — which is all of them.

**When NOT to use:** localnet spikes and throwaway experiments you'll delete. But
the moment a change is bound for devnet-shared or mainnet, this skill applies.

## The Pre-Launch Gate

**Step 0 is not optional: clear the Definition of Done first.** This checklist is
*additional* launch risk-control, not a substitute for the engineering bar. Run the
DoD gate for the layers you touched — `fullstack-standard` →
`references/definition-of-done.md` — then walk the sections below.

### Code & correctness (defer to DoD)
- [ ] Definition of Done gate is green for every layer touched (lint at zero
      tolerance, types, hermetic unit tests, integration/`anchor test`, build,
      format, secret scan, verified end-to-end). Do not proceed on a yellow gate.
- [ ] No `unwrap()`/`expect()` in runtime paths, no `any`/`!`, no `print()`/
      `console.log` debug lines shipped.
- [ ] Error handling covers the failure modes, not just the happy path.

### On-chain safety (Anchor / Solana — the highest-stakes surface)
- [ ] Every account constraint validated: `has_one`, `seeds`, `bump`, `owner`,
      signer checks. Client input treated as hostile (`backend-standards.md`).
- [ ] Failure-case tests pass: bad signer, wrong PDA, insufficient funds, replayed
      or reordered instructions — not just the happy path.
- [ ] Rent, CPI, and signer/authority handling are explicit.
- [ ] **Upgrade-authority policy is deliberate and documented** (multisig / timelock
      / burned). If mutable, the upgrade key is a hardware/multisig key, never a hot
      key. Decision recorded via `documentation-and-adrs`.
- [ ] Program ID and the deployed `.so` are pinned; the exact commit is tagged.
- [ ] An on-chain **pause/admin switch** exists for anything holding value (your
      kill switch — see Feature Gates).

### Security & secrets
- [ ] No secrets, keypairs, or seed phrases in the diff or in client bundles
      (`git diff --staged` reviewed). Keys come from env / a signer, never source.
- [ ] `cargo audit` / `pnpm audit` clean of critical & high; `pip` deps checked.
- [ ] Input validation and authz on every server endpoint; CORS pinned to specific
      origins; rate limiting on auth paths. (See `security-and-hardening`.)

### Web (if a frontend ships — `frontend-standards.md`)
- [ ] Responsive, keyboard-navigable, WCAG AA contrast, works in light + dark, no
      layout shift; one clear CTA per marketing page.
- [ ] Only public keys/endpoints reach the browser — nothing sensitive.
- [ ] Core Web Vitals within "Good"; bundle within budget; images optimized.

### Infrastructure & observability
- [ ] Production env vars set (in config, not typed from memory).
- [ ] RPC endpoint(s) chosen and rate-limit-aware; commitment level decided.
- [ ] Migrations (or account init) applied or ready; a health check responds.
- [ ] Logging via `tracing` (Rust) / `loguru` (Python) / project logger, flowing to
      a place you can read. Dashboards exist **before** launch
      (see `observability-and-instrumentation`).

### Docs
- [ ] ADRs written for the irreversible decisions (`documentation-and-adrs`).
- [ ] README / changelog current; IDL committed if it changed.

## Feature Gates (the kill switch)

Decouple *deploy* from *release* so a bad path can be turned off without a redeploy.

**On-chain:** a config PDA with an admin-set `paused: bool` (and per-feature flags),
checked at the top of each instruction. Flipping it is one signed transaction — your
sub-minute kill switch for a live program.

```rust
require!(!ctx.accounts.config.paused, MarketplaceError::Paused);
```

**Off-chain (server/web):** gate new paths behind a typed flag resolved from config,
not a hardcoded boolean. Test both states in CI.

```typescript
if (flags.stakedSettlement) {
  return await buildStakedSettleTx(job);
}
return await buildStandardSettleTx(job); // existing, known-good path
```

**Rules:** every flag/switch has an owner and an expiry; remove it (and the dead
path) within ~2 weeks of full rollout; don't nest flags into exponential combos;
test on *and* off states in CI.

## Staged Rollout — localnet → devnet → mainnet

Never big-bang to mainnet. Promote through environments, monitoring at each gate.

```
1. LOCALNET  (solana-test-validator)
   └── `anchor test` full suite incl. failure cases
   └── Manual smoke of the critical flow against a local validator

2. DEVNET    (shared, real network conditions, worthless SOL)
   └── `anchor deploy --provider.cluster devnet`  (record program ID + commit)
   └── Run the client SDK and web app against devnet
   └── Watch tx success rate, program logs, latency — 24h soak
   └── Advance only if the thresholds below are green

3. MAINNET — deploy DARK (program live, feature switch OFF / value caps low)
   └── `anchor deploy --provider.cluster mainnet-beta` from a tagged commit
   └── Verify program ID matches; verify buildable-from-source (verifiable build)
   └── No user funds flowing yet: pause flag ON

4. CANARY on mainnet (switch ON; low escrow caps / allowlist / small % of traffic)
   └── Compare canary vs. baseline: tx success, latency, error logs
   └── 24–48h window; advance only on green

5. GRADUAL increase (raise caps / widen allowlist / 25% → 50% → 100%)
   └── Same monitoring at each step; able to step back a level at any time

6. FULL rollout
   └── Monitor 1 week; then remove the feature switch and dead path
```

### Rollout Decision Thresholds

| Metric | Advance (green) | Hold & investigate (yellow) | Roll back (red) |
|---|---|---|---|
| Tx success rate | Within 1% of baseline | 1–5% below baseline | >5% below baseline |
| Program errors (custom error logs) | No new error codes | New code at <0.1% of txs | New code at >0.1% of txs |
| P95 confirmation / API latency | Within 20% of baseline | 20–50% above | >50% above |
| Client JS errors | No new types | New at <0.1% of sessions | New at >0.1% |
| Business/economic metric | Neutral or positive | Decline <5% (may be noise) | Decline >5%, or any fund discrepancy |

### Roll back immediately if
- Tx success rate drops sharply or custom-error logs spike.
- **Any accounting discrepancy** in escrow/treasury balances — treat as sev-1.
- P95 latency regresses >50%, or user reports spike.
- A security issue is discovered in the deployed program or endpoint.

## Monitoring & Observability

Set dashboards up **before** you launch — you can't debug what you can't see. Detail
in `observability-and-instrumentation`; watch at minimum:

```
On-chain:
├── Transaction success / failure rate (by instruction)
├── Custom program-error codes (which constraint is failing)
├── Confirmation latency and slot lag
├── Treasury / escrow PDA balances vs. expected (accounting invariant)
└── Emitted program events / logs

Service (Rust/Python/TS backend):
├── Error rate by endpoint; RED metrics
├── RPC call latency and rate-limit/429s from the RPC provider
├── CPU / memory / queue depth
└── Structured logs via tracing / loguru (never stdout prints)

Client (web):
├── Core Web Vitals (LCP, INP, CLS)
├── JS errors and wallet-adapter failures
└── Client-observed tx submission success
```

Server error reporting: report typed errors to your tracker with request context,
and never leak internals to the caller.

```rust
// Report with context; return a typed, opaque error to the client.
tracing::error!(instruction = "settle", job = %job_pubkey, error = %e, "settle failed");
return Err(MarketplaceError::SettlementFailed.into());
```

### Post-Launch Verification (first hour)

```
1. Health endpoint / RPC getHealth returns OK
2. Error dashboard: no new program-error codes or endpoint errors
3. Latency dashboard: no regression
4. Run the critical flow for real (submit → fund → settle on the target cluster)
5. Confirm treasury/escrow balances reconcile
6. Confirm logs are flowing and readable
7. Dry-run the kill switch (flip pause on a canary and back)
```

## Rollback Strategy

Write the rollback plan **before** deploying. On-chain, "revert" is not a git revert.

```markdown
## Rollback Plan for <release>

### Trigger conditions
- Tx success rate > 5% below baseline, or new custom-error code > 0.1% of txs
- Any escrow/treasury accounting discrepancy
- P95 latency > <X>, or a security issue in the deployed code

### Steps (fastest first)
1. KILL SWITCH: set `config.paused = true` via one signed admin tx  (< 1 min).
   Stops the bleeding without a redeploy.
2. PROGRAM: redeploy the previous, tagged `.so` to the same program ID
   (`anchor upgrade` / `solana program deploy --program-id <id> prev.so`),
   using the upgrade authority (multisig/timelock as configured).  (< 15 min,
   only if upgrade authority is retained.)
3. OFF-CHAIN: redeploy the previous service/web build (previous tag / flag off).
4. Verify: health check, error dashboard, replay the critical flow, reconcile
   balances.
5. Communicate: note the rollback and cause; open a follow-up.

### Data considerations
- Account layout change from <migration>: is it forward-only? If so, the previous
  program MUST still read new accounts, or step 2 is unsafe — plan the migration to
  be additive/back-compatible before shipping.
- Escrow already in flight when paused: how it drains/refunds — decide up front.

### Time to rollback
- Kill switch: < 1 min · Program redeploy: < 15 min · Service/web: < 5 min
```

## Ephemeral-Node Deploy Discipline (critical)

Most GPU/compute nodes use **ephemeral container storage** — code or config that
lives only on the node is lost on restart or redeploy (`fullstack-standard` → deploy
discipline). Before you stop, restart, or redeploy ANY node you worked on directly:

1. `git status` / `git diff` on the node's checkout.
2. Commit to a branch and push, **or** copy the file back to the local repo and
   commit it there.
3. Confirm `git status` is clean on the node.

The repo is the source of truth. If it isn't committed and pushed, redeploying the
node deletes it.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "It passed on devnet, mainnet will be fine." | Mainnet has real value, real MEV, real congestion, and no undo. Deploy dark, canary, watch. |
| "This program doesn't need a pause switch." | Anything custodying SOL needs a sub-minute kill switch. You will want it exactly once, and that once matters. |
| "We'll burn the upgrade authority later / never decide." | Upgrade-authority policy is a launch decision with an ADR. 'Undecided' means a hot key can rewrite your program. |
| "Monitoring is overhead." | Without it you learn about the drained treasury from a user, not a dashboard. |
| "We'll add dashboards after launch." | You can't debug the first hour with dashboards that don't exist yet. Build them before. |
| "Rolling back is admitting failure." | Rolling back is the responsible move. Shipping a broken settlement path is the failure. |
| "It's on the node, we're fine." | Ephemeral storage. Redeploy wipes it. Commit and push first. |

## Red Flags

- Deploying to mainnet without a written, tested rollback plan.
- A value-holding program with no pause switch and no upgrade-authority ADR.
- Big-bang mainnet deploy with no devnet soak or canary.
- No monitoring / no dashboards live before launch.
- No one watching the first hour after a mainnet release.
- Production config or keys typed from memory instead of from managed config.
- Restarting a compute node without committing its working changes first.
- "It's Friday afternoon, let's push to mainnet."

## Verification

Before deploying:
- [ ] Definition of Done gate green for every layer (`references/definition-of-done.md`).
- [ ] Pre-launch gate above completed (on-chain, security, web, infra, docs).
- [ ] Feature/pause switch wired and tested in both states.
- [ ] Rollback plan written **and** its kill switch dry-run tested.
- [ ] Dashboards live and reachable; alerts point at symptoms.
- [ ] Deploying from a tagged commit; program ID and `.so` pinned.

After deploying (per stage):
- [ ] Health / `getHealth` OK; program ID matches expected.
- [ ] No new custom-error codes; error and latency within green thresholds.
- [ ] Critical flow run for real on the target cluster; balances reconcile.
- [ ] Logs flowing; kill switch verified ready.
- [ ] Any node worked on has its changes committed and pushed.

## See Also

- `fullstack-standard` — always-on core standard; **Step 0 is its Definition of Done
  gate** (`references/definition-of-done.md`) and its deploy/node discipline.
- `fullstack-standard` → `references/backend-standards.md` (Anchor/on-chain safety),
  `references/frontend-standards.md` (web launch quality).
- `observability-and-instrumentation` — the dashboards, RED metrics, and alerts this
  skill assumes are already in place.
- `security-and-hardening` — pre-launch security checks and secret hygiene.
- `documentation-and-adrs` — record the upgrade-authority and rollout decisions.
- `debugging-and-error-recovery` — when the launch goes red, before you roll back.
