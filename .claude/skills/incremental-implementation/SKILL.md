---
name: incremental-implementation
description: Delivers changes in thin vertical slices — one compilable increment, one commit — across eonedge's Rust/Anchor/TS/Astro/Next/Python stack. Use when implementing any feature or change that touches more than one file. Use when you're about to write a large amount of code at once, or when a task feels too big to land in one step.
---

# Incremental Implementation

## Overview

Build in thin vertical slices — implement one piece, test it, verify it, commit it, then expand. Never implement an entire feature in one pass. Each increment leaves the tree compilable and green. This is the execution discipline that makes large features manageable and rollbacks painless. Velocity comes from small, correct, well-typed increments — not from skipping the gate.

## When to Use

- Implementing any multi-file change or a task from a `tasks/todo.md` breakdown
- Building a new feature across on-chain program, server, and UI
- Refactoring existing code
- Any time you're tempted to write more than ~100 lines before testing

**When NOT to use:** Single-file, single-function changes where scope is already minimal.

## The Increment Cycle

```
┌──────────────────────────────────────┐
│                                      │
│   Implement ──→ Test ──→ Verify ──┐  │
│       ▲                           │  │
│       └───── Commit ◄─────────────┘  │
│              │                       │
│              ▼                       │
│          Next slice                  │
│                                      │
└──────────────────────────────────────┘
```

For each slice:

1. **Implement** the smallest complete piece of functionality.
2. **Test** — run (or write) the relevant test, failure cases included.
3. **Verify** — keep it compilable: types + lint + tests green for the layer you touched.
4. **Commit** — one logical change, one Conventional Commit (see Rule 6).
5. **Move to the next slice** — carry forward, don't restart.

## Slicing Strategies

### Vertical Slices (Preferred)

Build one complete path through the stack. Each slice delivers working end-to-end functionality:

```
Slice 1: Register identity (Anchor account layout + init ix + typed API + form)
    → anchor test green, user can register via the UI on devnet

Slice 2: List jobs (query + typed API response + UI list)
    → tests pass, user sees their jobs

Slice 3: Submit a job (job account + submit ix + API + submit form)
    → tests pass, job lands on-chain

Slice 4: Cancel a job (close ix + API + UI + confirm)
    → failure cases tested (wrong signer, wrong PDA), flow complete
```

### Contract-First Slicing

When backend and frontend proceed in parallel, define the type contract once and let both sides depend on it:

```
Slice 0: Define the exported domain types (Rust *-types crate or shared TS types + IDL)
Slice 1a: Implement backend against the contract + tests (happy + failure)
Slice 1b: Implement frontend against mock data matching the contract — importing the exported types, never redefining them
Slice 2: Integrate and test end-to-end
```

### Risk-First Slicing

Tackle the riskiest / most uncertain piece first — prove it before building on it:

```
Slice 1: Prove the CPI + signer/PDA derivation works (highest risk)
Slice 2: Build the job flow on the proven instruction
Slice 3: Add rent reclamation and reconnection edge cases
```

If Slice 1 fails, you find out before investing in 2 and 3.

## Implementation Rules

### Rule 0: Simplicity First

Before writing code, ask: "What is the simplest thing that could work?" Layers must earn their keep — no service/repository/DI indirection unless the code is genuinely simpler with it. Map requests directly to handlers; access the DB directly (raw `sqlx`).

After writing, review against:
- Can this be done in fewer lines?
- Does this abstraction earn its complexity, or would a staff engineer say "why didn't you just..."?
- Am I building for hypothetical future requirements, or the current task?

```
SIMPLICITY CHECK:
✗ Generic trait + builder for one instruction        ✓ One instruction handler
✗ Service layer wrapping a single sqlx query          ✓ Query in the handler
✗ Config-driven form engine for three forms           ✓ Three form components
```

Three similar lines beat a premature abstraction. Implement the naive, obviously-correct version first; optimize only after correctness is proven with tests.

### Rule 0.5: Scope Discipline

Touch only what the task requires. Do NOT:
- "Clean up" code adjacent to your change
- Refactor imports in files you're not modifying
- Remove comments you don't fully understand
- Add features not in the spec because they "seem useful"
- Modernize syntax in files you're only reading

If you notice something worth improving outside scope, note it — don't fix it:

```
NOTICED BUT NOT TOUCHING:
- programs/foo/src/util.rs has an unused import (unrelated to this task)
- The API error messages could be clearer (separate task)
→ Want me to file these as tasks?
```

### Rule 1: One Thing at a Time

Each increment changes one logical thing. Don't mix concerns.

**Bad:** One commit that adds an instruction, refactors an existing one, and bumps the Anchor version.
**Good:** Three commits — one per change.

### Rule 2: Keep It Compilable

After each increment the project must build and existing tests must pass. Never leave the tree broken between slices. Run the check for the layer you touched — don't guess:

| Layer | Fast compile/type check | Tests |
|---|---|---|
| Rust / Anchor | `cargo check` | `cargo test` · `anchor test` (local validator) |
| Server / browser TS | `pnpm tsc --noEmit` | `pnpm test` |
| Python | `mypy`/`pyright` (if configured) | `pytest` |

If a check fails, fix it before moving on — use `debugging-and-error-recovery` if the failure isn't obvious. No `unwrap()`/`expect()`/`any`/`!`/`print()` sneaking in to make it compile; errors are typed (`thiserror`/`?`) and logged through the project logger (`tracing`/`loguru`).

### Rule 3: Feature Flags for Incomplete Features

If a feature isn't ready for users but you want to land increments, gate it behind an env-driven flag so incomplete work stays invisible:

```typescript
// WIP: off unless explicitly enabled
const ENABLE_JOB_SHARING = process.env.FEATURE_JOB_SHARING === "true";
if (ENABLE_JOB_SHARING) {
  // new sharing UI
}
```

```rust
// Rust: gate behind config read from env, default off
if config.feature_job_sharing {
    // new path
}
```

Secrets and flags come from the environment, never literals in source.

### Rule 4: Safe Defaults

New code defaults to safe, conservative, opt-in behavior:

```typescript
export function submitJob(data: JobInput, options?: { notify?: boolean }) {
  const shouldNotify = options?.notify ?? false; // opt-in
}
```

On-chain, "safe default" means deny-by-default: validate every account constraint (`has_one`, `seeds`, `bump`, `owner`, signer) and treat all client input as hostile.

### Rule 5: Rollback-Friendly

Each increment is independently revertable:
- Additive changes (new files, new instructions) revert cleanly.
- Modifications to existing code stay minimal and focused.
- DB migrations ship with rollback migrations; on-chain account layout changes are versioned deliberately.
- Don't delete something and replace it in the same commit — separate them.

### Rule 6: One Commit Per Task, Conventional

Land each completed slice as one atomic Conventional Commit on a typed branch — the repo is the source of truth:

- Branch: `feat/`, `fix/`, `docs/`, `chore/`, `refactor/`, `test/`.
- Message: `type(scope): description` — e.g. `feat(program): add identity PDA init instruction`.
- Never commit to the default branch directly; branch first. Commit/push only when the user asks.
- See `git-workflow-and-versioning` for atomic-commit detail.

## Working with Agents

When directing an agent to implement incrementally, be explicit about what is and isn't in scope for the slice:

```
"Implement Task 3 from tasks/todo.md.

Start with just the Anchor account layout and the submit instruction.
Don't touch the API or UI yet — next increment.

After implementing, run `cargo check` and `anchor test` to prove nothing
is broken, then commit as feat(program): ..."
```

## Increment Checklist

After each increment, verify (run each command only after a change that could affect it — a green run on unchanged code adds nothing):

- [ ] The change does one thing and does it completely
- [ ] Types check — `cargo check` / `pnpm tsc --noEmit`
- [ ] Lint clean at zero tolerance — `cargo clippy -- -D warnings` / `ruff check .` / `pnpm lint`
- [ ] Tests pass, failure cases included — `cargo test` / `anchor test` / `pytest` / `pnpm test`
- [ ] The new functionality works as expected (you actually drove it)
- [ ] Committed as one Conventional Commit on a typed branch

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll test it all at the end" | Bugs compound. A bug in Slice 1 makes Slices 2-5 wrong. Test each slice. |
| "It's faster to do it all at once" | It *feels* faster until something breaks and you can't find which of 500 lines did it. |
| "These changes are too small to commit separately" | Small commits are free. Large commits hide bugs and make rollbacks painful. |
| "I'll add the feature flag later" | If the feature isn't complete, it shouldn't be user-visible. Add the flag now. |
| "This refactor is small enough to include" | Refactors mixed with features make both harder to review and debug. Separate them. |
| "I'll just `unwrap()` to get it compiling" | That's a runtime panic waiting to happen. Type the error and `?` it now. |
| "Let me run the build again just to be sure" | After a green run, repeating the same command adds nothing unless the code changed. |

## Red Flags

- More than 100 lines written without running a check
- Multiple unrelated changes in one increment
- "Let me just quickly add this too" scope expansion
- Skipping test/verify to move faster
- Build or tests broken between increments
- Large uncommitted changes accumulating (and the repo is the source of truth)
- Building abstractions before the third use case demands it
- `unwrap()`/`expect()`/`any`/`!`/`print()` appearing in runtime paths
- Touching files outside task scope "while I'm here"
- Redefining an API shape on the client instead of importing the backend's exported type
- Running the same check twice with no intervening code change

## Verification

After completing all increments for a task:

- [ ] Each increment was individually tested and committed
- [ ] The full test suite (and `anchor test` where on-chain code changed) passes
- [ ] The build is clean for every layer touched
- [ ] The feature works end-to-end as specified — you drove the real flow, not just typecheck
- [ ] No uncommitted changes remain

## See Also

- Per-increment checks are the local gate. Before declaring the task done, run the full Definition of Done gate (`fullstack-standard` → `references/definition-of-done.md`).
- Get the slices from `planning-and-task-breakdown`; the vertical-slice plan feeds this cycle directly.
- Commit discipline: `git-workflow-and-versioning`. When a check fails: `debugging-and-error-recovery`.
- Backend rules (Rust/Anchor/Python typed errors, PDAs, `loguru`): `fullstack-standard` → `references/backend-standards.md`. Frontend rules (Astro/Next, import don't redefine types): `references/frontend-standards.md`.
