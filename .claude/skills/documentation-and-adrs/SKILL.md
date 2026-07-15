---
name: documentation-and-adrs
description: Records the reasoning behind technical decisions and keeps docs true to the code. Use when making an architectural decision, designing an on-chain program or account layout, choosing a framework/dependency, changing a public API or type contract, or recording context future engineers and agents will need. Use when you catch yourself explaining the same decision twice, or when a decision would be expensive to reverse (a deployed Solana program especially).
---

# Documentation and ADRs

## Overview

Document decisions, not just code. Code shows *what* was built; the highest-value
documentation captures *why* — the constraints, the alternatives you rejected, and
the trade-off you accepted. That context is what a future engineer or agent needs
and what git diffs can never reconstruct. In this workspace the rule is stronger:
**the repo is the source of truth** (`fullstack-standard` core philosophy). A
decision that lives only in your head, a chat, or a deployed node does not exist.
If it mattered enough to decide, it matters enough to commit.

## When to Use

- Designing an on-chain program: account layout, PDA seed scheme, authority model,
  upgrade-authority policy, treasury custody.
- Choosing a framework, crate, or major dependency (Anchor vs. native, Axum vs.
  Actix, Astro vs. Next for a given surface).
- Adding or changing a public API or a shared domain type — the contract other
  crates/clients depend on.
- Any decision that would be expensive to reverse (a mainnet program, a data model,
  a persisted account schema).
- Onboarding a new agent or human to a repo.
- When you find yourself explaining the same thing twice.

**When NOT to use:** Don't document self-evident code. Don't write comments that
restate what the code already says. Don't write ADRs for throwaway prototypes or
localnet spikes you'll delete. Ceremony is not the goal — captured reasoning is.

## Architecture Decision Records (ADRs)

ADRs capture the reasoning behind significant technical decisions. On a Solana stack
they matter most, because an on-chain design is close to irreversible once a program
holds real value — you cannot casually "refactor" a live account layout.

### When to Write an ADR

- Program architecture: Anchor vs. native, one program vs. many, CPI boundaries.
- Account / PDA design: seed scheme, who owns what, how identity and treasury are
  derived, rent strategy.
- Upgrade-authority policy: multisig, timelock, or burned (immutable) — and why.
- A shared type contract or SDK surface exposed to clients.
- Framework/hosting/infra choices, or any decision costly to reverse.

### ADR Template

Store ADRs in `docs/decisions/` with sequential numbering, committed alongside the
code they justify:

```markdown
# ADR-004: Derive treasury as a program-owned PDA, not a keypair

## Status
Accepted   (one of: Proposed | Accepted | Superseded by ADR-XXX | Deprecated)

## Date
2026-07-08

## Context
The compute-marketplace program must custody escrowed SOL between a job's funding
and its settlement. Requirements:
- No off-chain key may unilaterally move escrowed funds.
- Custody must be deterministic and verifiable on-chain by any client.
- Funds released only when the program's settlement instruction runs and every
  account constraint passes.

## Decision
Custody escrow in a PDA derived from `["treasury", job.key()]`, owned by the
program. The bump is stored on the job account. Only the settlement instruction,
gated by `has_one`/`seeds`/`bump` constraints, can sign for the PDA via
`invoke_signed`.

## Alternatives Considered

### A generated keypair held by the backend
- Pros: trivial to implement; familiar.
- Cons: a hot key that can move all escrow; a single leak drains the treasury;
  custody is off-chain and unverifiable.
- Rejected: violates "assume client input hostile" and puts funds behind one key.

### A single global treasury PDA for all jobs
- Pros: one account, simpler accounting.
- Cons: no per-job isolation; a bug in one settlement can touch unrelated escrow.
- Rejected: per-job PDAs give blast-radius isolation for near-zero extra cost.

## Consequences
- Every instruction touching escrow MUST validate `seeds`, `bump`, and `owner` —
  see `backend-standards.md` (Anchor/on-chain). Test the failure cases.
- Rent for one PDA per job; reclaimed on close. Documented in the rent ADR.
- Clients derive the treasury address deterministically; no address is trusted
  from client input.
```

### ADR Lifecycle

```
PROPOSED → ACCEPTED → (SUPERSEDED or DEPRECATED)
```

- **Never delete an old ADR.** It is the historical record of why the code looks
  the way it does. Deleting it re-opens a settled debate.
- When a decision changes, write a *new* ADR that references and supersedes the old
  one, and flip the old one's Status to `Superseded by ADR-XXX`.

## Inline Documentation

Comment the *why*, never the *what* (`backend-standards.md`, `frontend-standards.md`
both mandate this). One idiom per language:

**Rust — `///` for public items, `//` for non-obvious invariants:**

```rust
/// Settles a funded job: releases escrow to the provider and records the result
/// on-chain. Fails if the job is not in `Funded` state or the signer is not the
/// job's designated settler.
///
/// See ADR-004 for the treasury-PDA custody model.
pub fn settle(ctx: Context<Settle>, outcome: Outcome) -> Result<()> {
    // The bump is read from the job account, NOT re-derived, so a client cannot
    // smuggle a different treasury PDA past the `seeds` constraint.
    let bump = ctx.accounts.job.treasury_bump;
    // ...
}
```

**TypeScript — JSDoc on exported surface (the client's contract):**

```typescript
/**
 * Builds an unsigned `settle` transaction for a funded job.
 *
 * @param jobPubkey - The job account whose escrow is being settled.
 * @param outcome   - Provider result; must match the on-chain `Outcome` enum.
 * @returns An unsigned `Transaction`; the caller signs and sends it.
 * @throws {JobNotFundedError} If the job is not in the `Funded` state.
 */
export async function buildSettleTx(jobPubkey: PublicKey, outcome: Outcome): Promise<Transaction> {
  // ...
}
```

**Python — Google-style docstrings on public functions (`backend-standards.md`):**

```python
def submit_job(spec: JobSpec, funder: Keypair) -> Signature:
    """Fund and submit a compute job to the on-chain program.

    Args:
        spec: The validated job specification.
        funder: Keypair that pays escrow; must hold sufficient SOL.

    Returns:
        The confirmed transaction signature.

    Raises:
        InsufficientFundsError: If the funder cannot cover escrow plus rent.
    """
```

Do NOT: restate the code, leave `TODO` comments for things you should just do,
or keep commented-out blocks "just in case" — git remembers. Delete dead code.

### Document Known Gotchas

Pin known traps where the reader will hit them, and link the ADR:

```rust
// GOTCHA: `close = funder` reclaims rent to the funder, so this account is
// unusable after this instruction. Any later CPI referencing it will fail with
// AccountNotInitialized. See ADR-007 for the account-lifecycle model.
```

## API & Interface Documentation

The type is the contract (`fullstack-standard` type-driven design). Document at the
boundary, and let types carry the shape:

- **Rust / Anchor:** the generated **IDL** is the on-chain API surface — commit it
  and treat a breaking IDL change like a breaking API change (needs an ADR). Doc
  instructions and account structs with `///`.
- **Server TypeScript:** export shared types from one place; the frontend imports
  them, never redefines them (`backend-standards.md`). JSDoc the exported functions.
- **REST (if present):** an OpenAPI schema doubles as the doc and the contract test.
  Keep it in the repo, generated or hand-written, and current.

## README & Changelog

Every project's README covers: one-paragraph purpose; quick start with the **real**
commands for its stack (e.g. `anchor build && anchor test`, `pnpm dev`, `pip
install -e .`); a commands table; an architecture note that links to the ADRs. Keep
a `CHANGELOG.md` for shipped, user-facing changes (Added / Fixed / Changed), each
line referencing the PR or issue.

## Documentation for Agents

The repo is also the agent's memory. Keep these current so agents build the right
thing and don't re-litigate settled decisions:

- **CLAUDE.md / rules files** — project conventions the agent must follow.
- **Specs** — kept in sync so the agent builds to the current intent (see
  `spec-driven-development`).
- **ADRs** — stop agents (and humans) from re-deciding what's already decided.
- **Inline gotchas** — keep an agent out of a known trap.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The code is self-documenting." | Code shows *what*. It never shows *why*, which alternatives you rejected, or which constraint forced the shape. |
| "We'll document the program once the layout stabilizes." | An account layout on mainnet is near-irreversible. The ADR is what forces you to think before it's frozen. |
| "Nobody reads docs." | Agents read them every session. Your three-months-later self reads them. The next contributor reads them before touching your PDA. |
| "ADRs are overhead." | A 10-minute ADR prevents a 2-hour re-debate — and on-chain, prevents an unrecoverable redesign. |
| "It's in the chat / on the node." | Then it doesn't exist. The repo is the source of truth; a deployed node is ephemeral. |
| "Comments get outdated." | Comments on *why* are stable. Comments on *what* rot — which is exactly why you only write the former. |

## Red Flags

- An on-chain program with no ADR for its PDA/authority/upgrade model.
- A mainnet-bound decision that lives only in a chat or a commit message.
- A public API or shared type changed with no doc and no note to consumers.
- A README that doesn't say how to build, test, and run the project.
- Commented-out code instead of a deletion; `TODO`s that have aged for weeks.
- Docs that restate the code instead of explaining intent.
- An IDL breaking change shipped with no superseding ADR.

## Verification

- [ ] An ADR exists in `docs/decisions/` for every significant/irreversible
      decision, especially on-chain design, and each is **committed** (repo is truth).
- [ ] Superseded decisions link forward; no ADR was deleted.
- [ ] README covers quick start, the real stack commands, and an architecture note
      linking the ADRs.
- [ ] Public functions / instructions / exported types carry `why`-level docs; the
      Anchor IDL is committed and current.
- [ ] Known gotchas are pinned inline where the reader hits them.
- [ ] No commented-out code and no stale `TODO`s remain (`git diff` is clean of them).
- [ ] Rules files (CLAUDE.md) and specs reflect the current design.

## See Also

- `fullstack-standard` — core philosophy ("the repo is the source of truth",
  type-driven design, comment the *why*); the always-on bar.
- `fullstack-standard` → `references/backend-standards.md` — Rust/Anchor doc idioms,
  IDL as contract; `references/frontend-standards.md` — client-side comment rules.
- `spec-driven-development` — specs are living docs; keep them in sync.
- `api-and-interface-design` — the type/IDL contract this skill documents.
- `code-review-and-quality` — reviewers reject undocumented irreversible decisions.
