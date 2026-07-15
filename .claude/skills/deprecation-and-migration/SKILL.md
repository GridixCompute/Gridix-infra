---
name: deprecation-and-migration
description: Removes old systems and migrates consumers safely across eonedge's stack — on-chain program versions and account layouts, TypeScript SDK/API versions, Python services, and web endpoints. Use when replacing or sunsetting an API, program, feature, or library; migrating users from one implementation to another; consolidating duplicate code; upgrading a deployed Anchor program's state; or deciding whether to maintain or retire existing code. Use at design time to plan how a new system will eventually be removed.
---

# Deprecation and Migration

## Overview

Code is a liability, not an asset. Every line carries ongoing cost: bugs to fix,
dependencies to patch, security updates, and mental overhead for anyone working
nearby. The value is the *functionality*, never the code itself — when the same
functionality needs less code, less complexity, or a cleaner type, the old code
should go. Most builders are good at adding; few are good at removing. This skill
is the discipline of removing safely. **Deleting code that no longer earns its
keep is an achievement, not a loss.**

On this stack the stakes are sharper: a deployed on-chain program's account layout
and instruction interface are a public contract, and the SDK's exported types are
the contract every frontend imports. You cannot "just delete" either — you migrate.

## When to Use

- Replacing a system, API, program version, or library with a new one.
- Sunsetting a feature or consolidating duplicate implementations.
- Removing dead code nobody owns but consumers still depend on.
- **Upgrading a deployed Anchor program** whose account layout or instruction set
  is changing (this is a migration, not an edit).
- Versioning an SDK/API across a breaking change (pairs with `git-workflow-and-versioning`).
- At design time — planning how a new system will be removed in 3 years.

**When NOT to use:** ordinary refactors that keep the same external contract — that's
just normal work under `fullstack-standard`. This skill is for changes consumers
can observe.

## Core Principles

### Code is a liability

Value = functionality delivered, not lines written. Two implementations doing the
same thing is double the tests, docs, audits, and onboarding — and on-chain, double
the attack surface. When you can deliver the same behavior with less, remove the rest.

### Hyrum's Law makes removal hard

With enough consumers, *every* observable behavior gets depended on — including
bugs, an account's byte offset, an error's exact message, a PDA's seed order. This
is why deprecation demands **active migration**, not just an announcement. Clients
can't "just switch" when they depend on behaviors the replacement doesn't
replicate. On-chain this is absolute: a client that builds a transaction against
the old account layout doesn't degrade gracefully — it fails or resolves the wrong
PDA.

### Deprecation planning starts at design time

When building something new, ask "how do we remove this in 3 years?" Clean
interfaces, feature flags, a narrow surface, and a versioned program upgrade
authority make future removal cheap. Types that leak implementation everywhere make
it a nightmare — make illegal states unrepresentable and the seams stay clean.

## The Deprecation Decision

Before deprecating anything, answer:

```
1. Does this still provide unique value?          → yes: maintain. no: proceed.
2. How many consumers depend on it?               → quantify migration scope
   (clients pinned to a program ID, SDK importers, services calling the endpoint).
3. Does a replacement exist and is it proven?      → no: build it first. Never
   deprecate without a working, production/devnet-proven alternative.
4. What's the per-consumer migration cost?         → trivially automatable: do it.
   Manual + high-effort: weigh against maintenance cost.
5. What's the cost of NOT deprecating?             → security/audit risk, your
   time, the complexity tax on everything nearby.
```

## Compulsory vs Advisory

| Type | When | Mechanism |
|---|---|---|
| **Advisory** | Old system is stable; migration is optional | Deprecation notice, docs, `#[deprecated]` / `@deprecated` warnings, logged nudges. Consumers migrate on their timeline. |
| **Compulsory** | Old system has a security flaw, blocks progress, or its maintenance/audit cost is unsustainable | Hard deadline + provided migration tooling and docs. Removed by date X. |

**Default to advisory.** Reach for compulsory only when risk or cost justifies
forcing it — and compulsory means you *provide* the tooling, docs, and support, not
just a deadline. A security issue in a deployed program is the clearest compulsory
case; coordinate it through `SECURITY.md` channels, never a public issue.

## The Migration Process

### Step 1 — Build the replacement

Don't deprecate without a working alternative. It must cover all critical use
cases, ship with docs and a migration guide, and be **proven** — a new program
version runs on devnet against the real SDK; a new service runs in staging — not
"theoretically better."

### Step 2 — Announce and document

```markdown
## Deprecation Notice: place_order v1

**Status:** Deprecated as of 2026-03-01
**Replacement:** place_order v2 (market arg reordered; see guide)
**Removal:** Advisory until the v1 program authority is upgraded out — target v2.0
**Reason:** v1's account layout let a client-supplied authority reach the treasury
            path; v2 derives it as a PDA and re-checks has_one on every CPI.

### Migration Guide
1. Bump the SDK to `@eonedge/sdk@2` — it imports the new exported `PlaceOrderArgs`.
2. Rebuild transactions: `market` now precedes `side` in the instruction.
3. Point the client at the v2 program ID (config below).
4. Run the verification script against devnet: `pnpm migrate:check`.
```

Record the entry in the changelog as you make the change
(`git-workflow-and-versioning`), grouped under `Deprecated` / `Removed` with the
migration note.

### Step 3 — Migrate incrementally

One consumer at a time, never a big-bang cutover. For each:

```
1. Find every touchpoint with the deprecated system
   (rg for the old import / program ID / endpoint / account struct).
2. Update to the replacement.
3. Verify behavior matches — cargo test / anchor test / pnpm test, on devnet where on-chain.
4. Remove references to the old system.
5. Confirm no regressions (run the DoD gate for the layers touched).
```

**The Churn Rule:** if you own the infrastructure being deprecated, *you* migrate
its consumers — or ship a backward-compatible update that requires no migration.
Solo builder reality: "the consumers" are your own other repos and deployed
clients; migrate them yourself rather than leaving future-you a landmine. Don't
announce and walk away.

### Step 4 — Remove the old system

Only after all consumers have migrated:

```
1. Verify zero active usage — logs/metrics, on-chain program-account read counts,
   rg across every repo that could import it.
2. Remove the code.
3. Remove its tests, docs, config, and .env keys.
4. Remove the deprecation notices — they served their purpose.
5. Delete dead code fully — no commented-out "just in case" blocks (git remembers).
```

For a deployed program, "remove" means the upgrade that drops the old
instruction/account handling — and only once no live client hits it. An immutable
program can't be removed; that's why the layout is a design-time decision.

## Migration Patterns

### Strangler

Run old and new in parallel; shift traffic (or on-chain, shift clients) old → new
incrementally, then remove the old at 0%.

```
0% new / 100% old → 10% (canary) → 50% → 100% new / old idle → remove old
```

### Adapter

Translate the old interface to the new implementation so consumers keep the old
call signature while the backend moves. Keep it typed end-to-end — no `any` at the
seam.

```typescript
// old interface, new implementation — types stay the contract
class LegacyTaskClient implements OldTaskApi {
  constructor(private readonly next: NewTaskService) {}

  getTask(id: number): OldTask {
    const task = this.next.findById(String(id));   // new impl
    return toOldShape(task);                         // adapt at the boundary
  }
}
```

On-chain analogue: a v1 instruction handler that internally CPIs or delegates to
the v2 logic, so old clients keep working through one release window.

### Feature-flag migration

Switch consumers one at a time behind a flag (flag lifecycle lives in
`ci-cd-and-automation`):

```typescript
function taskService(userId: string): TaskService {
  return featureFlags.isEnabled("new-task-service", { userId })
    ? new NewTaskService()
    : new LegacyTaskService();
}
```

### On-chain state migration

Changing an account's layout on a deployed program is a **breaking (MAJOR)** change
(see `git-workflow-and-versioning`). Migrate the state deliberately:

```
1. Add a version discriminator field to the account (or use Anchor's account
   versioning) so old and new layouts are distinguishable on read.
2. Ship an upgrade: the program reads both old and new layouts (adapter in-program).
3. Provide a permissioned `migrate_account` instruction that rewrites an old
   account into the new layout, checking every constraint (owner, PDA seeds, bump,
   signer) — assume the caller is hostile.
4. Migrate accounts incrementally (lazily on next touch, or via a batched keeper).
5. Once zero old-layout accounts remain, ship the upgrade that drops old-layout
   handling and the migrate instruction.
```

Test the failure cases of `migrate_account` (already migrated, wrong owner, wrong
PDA) via `anchor test`, not just the happy path.

## Zombie Code

Code nobody owns but everybody depends on — unmaintained, no owner, accruing
vulnerabilities. Signs:

- No commits in 6+ months yet active consumers (or a live program clients still call).
- No assigned maintainer; failing tests nobody fixes.
- Dependencies with known CVEs nobody patches (a real audit risk on-chain).
- Docs referencing systems that no longer exist.

**Response:** either assign an owner and maintain it to the bar, or deprecate it
with a concrete migration plan. It cannot stay in limbo — investment or removal.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "It still works, why remove it?" | Unmaintained working code accrues security/audit debt silently. On-chain, that debt is exploitable. |
| "Someone might need it later" | If it's needed later, rebuild it from git history. Keeping it "just in case" costs more than rebuilding. |
| "The migration is too expensive" | Compare it to 2–3 years of maintaining two systems (double tests, double audits). Migration is usually cheaper. |
| "We'll plan deprecation after the new system ships" | By then you'll have new priorities and the seams will have leaked. Plan removal at design time. |
| "Consumers will migrate on their own" | They won't. Provide tooling and docs — or migrate them yourself (the Churn Rule). |
| "We can run both programs indefinitely" | Two programs doing one thing is double the attack surface, audits, and client confusion. |
| "Just change the account layout, it's my program" | The layout is the ABI. Old clients break. That's a MAJOR + a state migration, not an edit. |

## Red Flags

- Deprecating with no proven replacement available.
- A deprecation announcement with no migration tooling or docs.
- "Soft" deprecation that's been advisory for years with no progress.
- Zombie code: no owner, active consumers, unpatched CVEs.
- New features added to a deprecated system (invest in the replacement instead).
- Deprecating without measuring current usage; removing without verifying zero consumers.
- Changing a deployed account layout / instruction interface with no state-migration path.
- A breaking migration shipped without a major version bump or changelog note.

## Verification

After completing a deprecation:

- [ ] Replacement is production/devnet-proven and covers all critical use cases.
- [ ] Migration guide exists with concrete, copy-pasteable steps and examples.
- [ ] All active consumers migrated — verified by logs/metrics, on-chain usage, and `rg` across repos.
- [ ] For on-chain: zero accounts remain on the old layout before old-layout handling is dropped; `migrate_account` failure cases tested via `anchor test`.
- [ ] Old code, tests, docs, config, and `.env` keys fully removed — no commented-out blocks.
- [ ] No references to the deprecated system remain (`rg` clean); deprecation notices removed.
- [ ] The breaking change was versioned and changelogged (`git-workflow-and-versioning`); DoD gate green for layers touched.

## See Also

- `git-workflow-and-versioning` — a breaking migration is a MAJOR bump; tag it, changelog it under Deprecated/Removed with the migration note.
- `ci-cd-and-automation` — feature-flag lifecycle and cleanup; devnet/staging as the proving ground before cutover; governed program upgrades and rollback.
- `fullstack-standard` — the bar the replacement must meet. Backend/on-chain rules: `references/backend-standards.md`. Gate: `references/definition-of-done.md`.
- `security-and-hardening` — routing a security-driven (compulsory) deprecation through the right channel.
