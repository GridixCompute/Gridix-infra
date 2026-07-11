---
name: spec-driven-development
description: Writes a structured specification before any code exists — the shared source of truth for what's being built, why, and how we'll know it's done. Use when starting a new project, feature, or significant change and no spec exists yet. Use when requirements are unclear, ambiguous, or only exist as a vague idea, or when a change touches multiple files, crates, or a program's account layout.
---

# Spec-Driven Development

## Overview

Write a structured specification before writing any code. The spec is the shared source of truth between you and the human — it defines what we're building, why, and how we'll know it's done. Code without a spec is guessing, and on-chain code you guessed at can cost a redeploy or a migration.

The spec is not documentation written after the fact — that's a changelog. The spec's entire value is forcing clarity *before* the first Anchor account is laid out or the first Astro route is scaffolded. **The repo is the source of truth; the spec is the part of the repo that exists before the code does.**

## When to Use

- Starting a new project, program, or feature
- Requirements are ambiguous or incomplete
- The change touches multiple files, crates, or a program's account layout / instruction set
- You're about to make an architectural decision (a new PDA, a new service, a chain choice)
- The task would take more than ~30 minutes to implement

**When NOT to use:** single-line fixes, typo corrections, `cargo fmt` runs, or changes where requirements are unambiguous and self-contained. Simple tasks don't need a *long* spec, but they still need acceptance criteria — a two-line spec is fine.

## The Gated Workflow

Four phases. Do not advance until the current one is validated by the human.

```
SPECIFY ──→ PLAN ──→ TASKS ──→ IMPLEMENT
   │          │        │          │
   ▼          ▼        ▼          ▼
 Human      Human    Human      Human
 reviews    reviews  reviews    reviews
```

### Phase 1: Specify

Start with a high-level vision. Ask clarifying questions until requirements are concrete. If the ask itself is underspecified (no user, no "why now"), run `interview-me` first; if it's a raw idea, run `idea-refine` first. This skill consumes their confirmed output.

**Surface assumptions immediately.** Before writing any spec content, list what you're assuming:

```
ASSUMPTIONS I'M MAKING:
1. This is a Solana program (Anchor), not a raw SVM program
2. Target cluster is devnet first, mainnet-beta later
3. Identity/treasury are PDAs; no client-supplied authority addresses
4. The frontend is a static Astro site; no Next server runtime needed
5. Off-chain indexing is a Python service (loguru), not a TS worker
→ Correct me now or I'll proceed with these.
```

Don't silently fill in ambiguous requirements — assumptions are the most dangerous form of misunderstanding, and a wrong on-chain assumption is the most expensive one.

**Reframe vague instructions as testable success criteria:**

```
REQUIREMENT: "Make the RPC layer faster"

REFRAMED SUCCESS CRITERIA:
- getProgramAccounts p95 < 400ms against devnet
- SDK method resolves in < 1 round-trip (no N+1 account fetches)
- No unbounded getProgramAccounts scans (filtered by discriminator + memcmp)
→ Are these the right targets?
```

This lets you loop and problem-solve toward a clear goal instead of guessing what "faster" means.

**Write a spec covering the six core areas below.** Use the template — its Tech Stack, Commands, and Boundaries are pre-loaded with the house stack.

**Spec template:**

```markdown
# Spec: [Project/Feature Name]

## Objective
What we're building and why. Who is the user? What does success look like?
User stories or acceptance criteria. (Pull this from interview-me / idea-refine
output if it exists.)

## Layer
[ ] Backend (on-chain and/or off-chain)   [ ] Frontend   [ ] Full-stack
→ Backend work is held to `fullstack-standard` → references/backend-standards.md
→ Frontend work is held to `fullstack-standard` → references/frontend-standards.md

## Tech Stack
Pick only what this change actually needs — minimal abstraction applies here too.
- On-chain:   Rust + Anchor <ver>, Solana <cluster: devnet/mainnet-beta>
- Server:     Rust (Axum + Tokio, sqlx) OR Python (ruff + loguru) OR TS SDK
- Shared:     domain types in a `*-types` crate / one exported TS types module
- Frontend:   Astro 5 / Next 15 + Tailwind v4 (state which; static-first by default)
- Data:       [Postgres via sqlx / on-chain accounts / RPC]

## Commands
Full executable commands with flags — not just tool names.
Backend:
  Lint:   cargo clippy -- -D warnings   ·   ruff check .
  Format: cargo fmt --check             ·   ruff format --check .
  Types:  cargo check                   ·   mypy / pyright
  Test:   cargo test                    ·   pytest
  Chain:  anchor test   (local solana-test-validator)
  Build:  cargo build --release         ·   pip install -e .
Frontend:
  Lint:   pnpm lint      Format: pnpm prettier -c .    Types: pnpm tsc --noEmit
  Test:   pnpm test      E2E:    pnpm e2e (Playwright)  Build: pnpm build

## Project Structure
Where each layer lives. Example (adapt to the repo):
  programs/<name>/       → Anchor on-chain program
  crates/<name>-types/   → shared Rust domain types (the contract)
  crates/<name>-sdk/     → Rust/TS client SDK (exports types the frontend imports)
  services/<name>/       → off-chain service (Rust or Python)
  app/                   → Astro / Next frontend
  tests/                 → hermetic unit tests
  tests/integration/     → service/DB-dependent tests
  docs/                  → specs, intent, ideas

## Code Style
One real snippet beats three paragraphs. Match the surrounding file. Example:

  // Rust: typed errors, no unwrap() in runtime paths, ? to propagate
  #[derive(thiserror::Error, Debug)]
  pub enum JobError {
      #[error("job {0} not found")]
      NotFound(Pubkey),
  }
  pub fn load_job(acc: &AccountInfo) -> Result<Job, JobError> {
      Job::try_deserialize(&mut &acc.data.borrow()[..])
          .map_err(|_| JobError::NotFound(*acc.key))
  }

  Conventions: no `any`/non-null `!` in TS; type hints + Google docstrings in
  Python; comments explain *why*, not *what*; delete dead code.

## Testing Strategy
- Unit tests hermetic (no network/DB/wall-clock); aim >80% on new code.
- On-chain: `anchor test` against a local validator — test failure cases
  (bad signer, wrong PDA, insufficient funds), not just the happy path.
- Service/DB tests live in tests/integration/.
- Frontend: hermetic component tests + Playwright E2E where a flow matters.

## Boundaries
- Always:    run the DoD gate before "done"; PDAs for identity/treasury;
             validate every account constraint (has_one/seeds/bump/owner/signer);
             read secrets from env; conventional commits on a branch.
- Ask first: program account-layout changes, adding a dependency or a new chain,
             CI changes, anything touching mainnet, DB schema/migration changes.
- Never:     commit secrets/keys/seed phrases; unwrap()/expect() in runtime paths;
             trust client-supplied addresses where a PDA is expected; ship
             sensitive data to the browser; remove a failing test without approval.

## Success Criteria
Specific, testable conditions — how we know this is done. Numbers where possible.

## Open Questions
Anything unresolved that needs human input before Phase 2.
```

### Phase 2: Plan

With the validated spec, generate a technical implementation plan:

1. Identify the major components and their dependencies (program ↔ types crate ↔ SDK ↔ frontend)
2. Determine implementation order — the shared types crate and account layout usually come first, because everything downstream depends on them
3. Note risks and mitigations (a CPI edge case, a rent calculation, an RPC rate limit)
4. Identify what's parallelizable vs. sequential (frontend can start against a typed SDK stub while the program is finished)
5. Define verification checkpoints between phases

> If a `planning-and-task-breakdown` sibling skill exists, follow it for the dependency-graph and vertical-slicing mechanics — it is canonical and the bullets above are a lightweight summary. Save the plan to `tasks/plan.md` and the task list to `tasks/todo.md` (create `tasks/` if absent); downstream build commands expect these paths.

The plan must be reviewable: the human reads it and says "yes, that's the right approach" or "no, change X."

### Phase 3: Tasks

Break the plan into discrete, implementable tasks:

- Each completable in one focused session
- Each with explicit acceptance criteria and a verification step
- Ordered by dependency, not perceived importance
- No task touches more than ~5 files

**Task template:**
```markdown
- [ ] Task: [Description]
  - Acceptance: [What must be true when done]
  - Verify: [Command — e.g. `anchor test`, `cargo clippy -- -D warnings`, `pnpm build`]
  - Files: [Which files/crates will be touched]
```

### Phase 4: Implement

Execute tasks one at a time. Follow `test-driven-development` (write the failing test first — including the on-chain failure cases) and `incremental-implementation` (one small, gated increment at a time). Load only the spec sections and source files each task needs rather than the whole spec. If a build breaks, hand off to `debugging-and-error-recovery` if it exists rather than flailing.

## Keeping the Spec Alive

The spec is a living document, not a one-time artifact:

- **Update when decisions change** — if the account layout or data model must change, update the spec first, then implement.
- **Update when scope changes** — features added or cut are reflected in the spec.
- **Commit the spec** — it belongs in version control alongside the code (`docs/`). The repo is the source of truth.
- **Reference the spec in PRs** — link the spec section each PR implements.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "This is simple, I don't need a spec" | Simple tasks don't need *long* specs, but they still need acceptance criteria. A two-line spec is fine; zero is not. |
| "I'll write the spec after I code it" | That's a changelog, not a specification. The spec's value is forcing clarity *before* code — especially before an account layout is fixed. |
| "The spec will slow us down" | A 15-minute spec prevents hours of rework, and on-chain it can prevent a redeploy. Waterfall in 15 minutes beats debugging in 15 hours. |
| "Requirements will change anyway" | That's why the spec is a living document. An outdated spec still beats no spec. |
| "The user knows what they want" | Even clear requests carry implicit assumptions — chain, custody, data model. The spec surfaces them. |
| "I'll pick the stack as I go" | Stack choice is an architectural decision. Fixing it in the spec's Tech Stack section is cheaper than discovering the wrong one mid-build. |

## Red Flags

- Starting to write code without any written requirements
- Asking "should I just start building?" before defining what "done" means
- Implementing features not mentioned in any spec or task
- Making an architectural decision (new PDA, new service, new chain) without documenting it
- Skipping the spec because "it's obvious what to build"
- A spec with no Boundaries section, or Boundaries that omit the on-chain constraints
- Advancing to Plan before the human approved the spec

## Verification

Before proceeding to implementation, confirm:

- [ ] The spec covers all six core areas (Objective, Tech Stack, Commands, Structure, Code Style, Testing) plus Boundaries and Success Criteria
- [ ] The **Layer** is marked and points at the right standard (backend / frontend / full-stack)
- [ ] Success criteria are specific and testable (numbers where possible)
- [ ] Boundaries (Always / Ask first / Never) are defined and include the on-chain constraints
- [ ] Commands in the spec are the real house-stack commands, runnable as written
- [ ] The human has reviewed and approved the spec
- [ ] The spec is saved to a file in the repository (`docs/`)
- [ ] Before shipping the implementation, the Definition of Done gate is run for real — see `fullstack-standard` → `references/definition-of-done.md`

## See Also

- **`interview-me`** — upstream. Run first when the ask is underspecified; the spec's Objective consumes its confirmed intent.
- **`idea-refine`** — upstream. Run first on a raw idea; the spec consumes its one-pager and "Not Doing" list.
- **`test-driven-development`** / **`incremental-implementation`** — Phase 4 execution.
- **`fullstack-standard`** — the engineering bar every phase is held to; its `references/definition-of-done.md` is the ship gate, and its backend/frontend standards are what the spec's Layer points at.
