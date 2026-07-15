---
description: Implement tasks incrementally — build, test, verify, commit. Add "auto" to run the whole plan in one approved pass.
---

Invoke the `incremental-implementation` skill alongside `test-driven-development`.

## Modes

- **`/build`** — implement the *next* pending task, then stop (one slice at a time).
- **`/build auto`** — generate the plan if needed, get a single approval, then implement *every* task without stopping between them.

`$ARGUMENTS` selects the mode. Treat `auto` or `all` as autonomous mode; anything else (or empty) is default single-task mode. Autonomous mode is not faster *per task* — it runs the same test-driven loop — it only removes the human stepping *between* tasks.

## Default: one task

Pick the next pending task from the plan. Then:

1. Read the task's acceptance criteria
2. Load relevant context (existing code, patterns, shared types)
3. Write a failing test for the expected behavior — RED (`cargo test` / `pytest` / `pnpm test`; on-chain → `anchor test`)
4. Implement the minimum code to pass — GREEN
5. Run the full test suite to check for regressions
6. Verify it compiles: `cargo check` / `pnpm tsc --noEmit`
7. Commit with a Conventional Commit message on a `feat/`|`fix/`|… branch (never the default branch)
8. Mark the task complete and stop

## Autonomous: the whole plan (`/build auto`)

Collapses plan + build into one run. Removes the manual stepping between tasks — **not** the verification. Every task still earns a passing test and its own commit.

1. **Require a spec.** Look only at `SPEC.md` (repo root), `docs/SPEC.md`, or a file under `spec/`. A README does not count. If none exists, stop and tell the user to run `/spec` first — do not invent requirements.
2. **Clean baseline.** Run `git status --porcelain`. If there are uncommitted changes outside expected planning artifacts (`SPEC.md`, `tasks/plan.md`, `tasks/todo.md`), stop and ask how to handle them.
3. **Plan if needed.** If no `tasks/plan.md`, invoke `planning-and-task-breakdown`.
4. **Single checkpoint.** Present the full plan and wait for an unambiguous "approve"/"go"/"yes". Hedged responses are NOT approval. This is the only human gate. Commit a generated `tasks/plan.md` as one preparatory commit.
5. **Execute every task in dependency order.** For each: full loop above (RED → GREEN → regression → compile → commit → mark complete). Stage only the files that task touched plus its status update — never `git add -A` blindly.
6. **Stop and ask the user** when:
   - a test can't pass or the build breaks without an obvious fix → follow `debugging-and-error-recovery`
   - the spec is ambiguous or a task needs an undocumented decision
   - a task is high-risk/irreversible — key/authority changes, on-chain mainnet deploys, data migrations, anything touching secrets or a live node, or anything you can't undo with `git revert` → follow `doubt-driven-development` and get explicit sign-off
7. **Summarize at the end:** tasks completed, tests added, commits made, anything skipped or flagged.

Before reporting "done", run the Definition of Done gate (`fullstack-standard` → `references/definition-of-done.md`). If any step fails, follow `debugging-and-error-recovery`.
