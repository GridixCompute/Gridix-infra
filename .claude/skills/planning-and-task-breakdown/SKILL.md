---
name: planning-and-task-breakdown
description: Breaks work into ordered, vertically-sliced tasks with acceptance criteria for eonedge's Rust/Anchor/TS/Astro/Next/Python stack. Use when you have a spec or clear requirements and need implementable tasks. Use when a task feels too large to start, when you need to estimate scope, or when parallel work across sessions is possible.
---

# Planning and Task Breakdown

## Overview

Decompose work into small, verifiable tasks with explicit acceptance criteria before you touch code. Good breakdown is the difference between an agent that ships correct increments and one that produces a tangled mess. Every task must be small enough to implement, test, and land in one focused session — one branch, one clean commit. Planning is the task; implementation without a plan is just typing.

## When to Use

- You have a spec and need to break it into implementable units
- A task feels too large or vague to start
- Work spans layers (on-chain program + server + frontend) and order isn't obvious
- Work needs to be parallelized across sessions
- You need to communicate scope to a human before building

**When NOT to use:** Single-file changes with obvious scope, or when the spec already contains well-defined, correctly-ordered tasks.

## The Planning Process

### Step 1: Enter Plan Mode (read-only)

Before writing any code, operate read-only — the repo is the source of truth, so read it:

- Read the spec and the relevant code (on-chain program, server, SDK, or web).
- Identify existing patterns and conventions. Match them; don't invent a second style.
- Find the domain types crate/module — everything hangs off the type contract.
- Map dependencies between components; note risks and unknowns.

**Do NOT write code during planning.** The output is `tasks/plan.md` and `tasks/todo.md`, not implementation.

### Step 2: Identify the Dependency Graph

Map what depends on what. For this stack, types and on-chain state sit at the bottom:

```
Domain types crate  (*-types)  /  Anchor account layouts + PDAs
    │
    ├── On-chain program (instructions, constraints)
    │       │
    │       └── Server SDK / API (Rust Axum or server TS, exports types)
    │               │
    │               ├── Frontend API client (imports backend types — never redefine)
    │               │       │
    │               │       └── UI components (Astro / Next)
    │               │
    │               └── Validation / typed errors (thiserror / Zod)
    │
    └── Migrations / seed / IDL generation
```

Implementation order follows the graph bottom-up: define the type contract and on-chain state first, build UI last.

### Step 3: Slice Vertically

Don't build all the on-chain code, then all the API, then all the UI. Build one complete path through the stack at a time — each slice delivers working, testable functionality.

**Bad (horizontal slicing):**
```
Task 1: Build the entire Anchor program
Task 2: Build all API endpoints
Task 3: Build all UI
Task 4: Connect everything (and discover the contract was wrong)
```

**Good (vertical slicing):**
```
Task 1: User can register an identity PDA (account layout + init ix + API + registration UI)
Task 2: User can fund a treasury PDA (state + deposit ix + API + deposit UI)
Task 3: User can submit a job (job account + submit ix + API + submit form)
Task 4: User can view job status (query + typed API response + status view)
```

Each vertical slice is independently verifiable and matches the one-commit-per-task rhythm the build phase runs on.

### Step 4: Write Tasks

Each task follows this structure. Verification commands come from the user's stack, not npm/jest:

```markdown
## Task [N]: [Short descriptive title — no "and"]

**Description:** One paragraph explaining what this task accomplishes.

**Layer:** on-chain | server | frontend | full-stack (name the standard it answers to)

**Acceptance criteria:**
- [ ] [Specific, testable condition]
- [ ] [Specific, testable condition]

**Verification (run for real):**
- [ ] Lint clean: `cargo clippy -- -D warnings` | `ruff check .` | `pnpm lint`
- [ ] Types: `cargo check` | `pnpm tsc --noEmit`
- [ ] Tests: `cargo test` | `pytest` | `pnpm test` (failure cases too, not just happy path)
- [ ] On-chain (if applicable): `anchor test` against local `solana-test-validator`
- [ ] Manual: [what you actually drove — ran the ix on devnet, loaded the page]

**Dependencies:** [Task numbers, or "None"]

**Files likely touched:**
- `programs/<name>/src/instructions/...rs`
- `crates/<name>-types/src/...rs` (or shared TS types)
- `tests/...`

**Estimated scope:** [S: 1-2 files | M: 3-5 files | L: 5-8, consider splitting]

**Commit:** `type(scope): description` on a `feat/`|`fix/`|... branch (Conventional Commits).
```

### Step 5: Order and Checkpoint

Arrange tasks so that:

1. Dependencies are satisfied (type contract and on-chain state first).
2. Each task leaves the system compilable and green — never a broken tree between tasks.
3. Verification checkpoints occur after every 2-3 tasks.
4. High-risk / high-uncertainty tasks are early (fail fast — prove the CPI, the PDA derivation, the WebSocket before building on them).

Add explicit checkpoints:

```markdown
## Checkpoint: After Tasks 1-3
- [ ] Full gate green for touched layers (see Definition of Done)
- [ ] Program builds and `anchor test` passes (happy + failure cases)
- [ ] Core user flow works end-to-end on devnet
- [ ] Review with human before proceeding
```

## Task Sizing Guidelines

| Size | Files | Scope | Example |
|------|-------|-------|---------|
| **XS** | 1 | Single fn / config / constraint | Add a `has_one` check to an instruction |
| **S** | 1-2 | One component or endpoint | Add one typed API route |
| **M** | 3-5 | One feature slice | Identity registration PDA + API + form |
| **L** | 5-8 | Multi-component feature | Job submission with validation and status polling |
| **XL** | 8+ | **Too large — break it down** | — |

An agent performs best on S and M tasks. If a task is L or larger, split it.

**Break a task down further when:**
- It would take more than one focused session (~2+ hours of agent work).
- You can't state acceptance criteria in 3 or fewer bullets.
- It touches two independent subsystems (e.g., on-chain program and marketing site).
- The title contains "and" (a sign it's two tasks).

## Output Files

- **Plan document:** `tasks/plan.md`.
- **Task list:** checklist-style `tasks/todo.md`.

Create `tasks/` if it doesn't exist. These paths are the convention the `/build` flow and downstream tooling expect. The repo is the source of truth — a plan that lives only in chat doesn't exist.

## Plan Document Template

```markdown
# Implementation Plan: [Feature/Project Name]

## Overview
[One paragraph on what we're building and why]

## Architecture Decisions
- [Decision + one-sentence rationale — especially any abstraction, which must earn its keep]
- [Which types crate/module owns the contract]

## Task List

### Phase 1: Type contract + on-chain foundation
- [ ] Task 1: ...
- [ ] Task 2: ...
### Checkpoint: Foundation
- [ ] Gate green, `anchor test` passes

### Phase 2: Server + API (exports types)
- [ ] Task 3: ...
### Checkpoint: API
- [ ] Typed end-to-end, integration tests pass

### Phase 3: Frontend (imports types)
- [ ] Task 4: ...
### Checkpoint: Complete
- [ ] All acceptance criteria met, Definition of Done green, ready for review

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| [e.g. CPI signer semantics unclear] | High | Prove it in Task 1 (risk-first) |

## Open Questions
- [Question needing human input — don't invent requirements]
```

## Parallelization Opportunities

- **Safe to parallelize:** Independent feature slices, tests for already-implemented features, docs, the marketing site vs. the program.
- **Must be sequential:** On-chain account layout changes, migrations, shared type-crate edits, anything mutating shared state.
- **Needs coordination:** Anything sharing an API contract — define the exported types first, then let backend and frontend proceed against that contract (backend implements it, frontend imports it; the client never redefines the shape).

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll figure it out as I go" | That's how you get a tangled mess and rework. 10 minutes of planning saves hours. |
| "The tasks are obvious" | Write them down anyway. Explicit tasks surface hidden dependencies and forgotten failure cases. |
| "Planning is overhead" | Planning is the task. Implementation without a plan is just typing. |
| "I can hold it all in my head" | Context windows are finite and the repo is the source of truth. Written plans survive session boundaries and compaction. |
| "I'll define the types once I start coding" | The type contract IS the plan for this stack. Decide it before you slice. |

## Red Flags

- Starting implementation with no written task list
- Tasks that say "implement the feature" with no acceptance criteria
- No verification commands in a task (or generic `npm test` instead of the real stack commands)
- Every task is XL-sized
- No checkpoints between phases
- Dependency order ignored — UI planned before the type contract or on-chain state
- A task whose title contains "and"

## Verification

Before starting implementation, confirm:

- [ ] Every task has acceptance criteria and a real stack verification command
- [ ] Task dependencies are identified and ordered bottom-up (types/on-chain first)
- [ ] No task touches more than ~5 files (else split it)
- [ ] Slices are vertical — each leaves the system compilable and demonstrable
- [ ] Checkpoints exist between phases
- [ ] The human has reviewed and approved the plan

## See Also

- Acceptance criteria are per-task ("did we build the right thing?"). They sit on top of the project-wide gate. Run the Definition of Done gate before any task counts as done (`fullstack-standard` → `references/definition-of-done.md`).
- Execute the plan with `incremental-implementation` — one thin slice, one commit, at a time.
- Curate what each task's session sees with `context-engineering`.
- Follow `fullstack-standard` for the core philosophy (minimal abstraction, type-driven design) that shapes every task.
