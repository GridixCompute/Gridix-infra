---
name: test-driven-development
description: Drives development with tests across the eonedge stack — Rust/Anchor, Python, and TypeScript/Astro/Next. Use when implementing any logic, fixing any bug, or changing any behavior. Use when you need to prove code works, when a bug report arrives, or when you're about to modify existing functionality. Covers red-green-refactor, the Prove-It reproduction pattern, and the hermetic-unit vs on-chain/integration split.
---

# Test-Driven Development

## Overview

Write a failing test before writing the code that makes it pass. For bug fixes, reproduce the bug with a test before attempting a fix. Tests are proof — "seems right," "cargo check passed," and "the types line up" are not done. On-chain especially: an untested failure path is an exploit waiting for a hostile client. A repo with good tests is your superpower; a repo without them is a liability. **If it isn't proven by a test, it doesn't work.**

## When to Use

- Implementing any new logic or behavior (a handler, an instruction, a transform)
- Fixing any bug (the Prove-It Pattern)
- Modifying existing functionality or refactoring
- Adding edge-case / failure-path handling — for Anchor this is mandatory, not optional
- Any change that could break existing behavior

**When NOT to use:** Pure config changes, docs, or static content with no behavioral impact. Renaming/formatting/file moves with no logic change.

This is full-stack. Backend commands and on-chain rules defer to `fullstack-standard` → `references/backend-standards.md`; frontend/browser rules to `references/frontend-standards.md`.

## The TDD Cycle

```
    RED                GREEN              REFACTOR
 Write a test    Write minimal code    Clean up the
 that fails  ──→  to make it pass  ──→  implementation  ──→  (repeat)
      │                  │                    │
      ▼                  ▼                    ▼
   Test FAILS        Test PASSES         Tests still PASS
```

### Step 1: RED — Write a Failing Test

Write the test first. It must fail. A test that passes immediately proves nothing — it tests nothing you didn't already have.

```rust
// RED: fails because `create_task` does not exist yet.
#[test]
fn creates_task_with_default_status() {
    let task = create_task(NewTask { title: "Buy groceries".into() });
    assert_eq!(task.title, "Buy groceries");
    assert_eq!(task.status, Status::Pending);
}
```

Run it and watch it fail: `cargo test creates_task_with_default_status` (or `pytest -k ...`, `pnpm test`). Confirm it fails for the *right reason* (missing behavior), not a typo or a compile error elsewhere.

### Step 2: GREEN — Make It Pass

Write the minimum code to make the test pass. Do not over-engineer, and stay on the bar — no `unwrap()`/`expect()` in a runtime path, no `any`, errors typed:

```rust
// GREEN: minimal, typed. Errors via thiserror + `?`, never unwrap in runtime paths.
pub fn create_task(input: NewTask) -> Task {
    Task { id: TaskId::new(), title: input.title, status: Status::Pending }
}
```

### Step 3: REFACTOR — Clean Up

With tests green, improve without changing behavior: extract shared logic, improve naming, remove duplication, tighten types so illegal states are unrepresentable. Run the tests after every refactor step to confirm nothing broke.

## The Prove-It Pattern (Bug Fixes)

When a bug is reported, **do not start by trying to fix it.** Start by writing a test that reproduces it.

```
Bug report ──→ Write a test that demonstrates the bug ──→ Test FAILS (bug confirmed)
   ──→ Implement the fix ──→ Test PASSES (fix proven) ──→ Full suite (no regressions)
```

```python
# Bug: "completing a task doesn't set completed_at"
# Step 1: reproduction test — must FAIL against current code
def test_complete_sets_completed_at():
    task = create_task(title="Test")
    done = complete_task(task.id)
    assert done.status == "completed"
    assert done.completed_at is not None  # fails → bug confirmed

# Step 2: fix the code so the test passes.
# Step 3: rerun `pytest` — green means fixed AND guarded against regression.
```

A bug fix without a failing-first reproduction test is not a fix; it's a guess that happened to compile.

## Hermetic Units vs. Integration / On-Chain

The single most important split in this repo. Keep the two tiers physically separate.

```
Is it pure logic — a transform, a validation, a PDA derivation, a serializer?
  → Hermetic UNIT test. No network, no live DB, no validator, no wall clock.
     Rust: cargo test   ·   Python: pytest   ·   TS: pnpm test

Does it cross a real boundary — the chain, a DB, an RPC, the browser?
  → INTEGRATION test, in a SEPARATE dir/suite.
     Anchor program:  anchor test  (spins a local solana-test-validator)
     Python service:  pytest tests/integration
     Web flow:        pnpm e2e / Playwright
```

- **Hermetic units** are the vast majority of the suite: milliseconds, deterministic, no external service. A unit test that needs a running validator or RPC is misfiled — move it to integration.
- **Anchor / on-chain**: `anchor test` runs against a local validator. **Test the failure cases, not just the happy path** — bad signer, wrong PDA / seeds / bump, missing `has_one`, wrong `owner`, insufficient funds, rent not met. Assume every client input is hostile; each account constraint deserves a test that proves it rejects the hostile case.
- **Web**: unit-test the pure logic (`pnpm test`); drive the actual page/flow with `pnpm e2e` or Playwright. Typecheck is not verification — you must exercise the flow.

### The Beyoncé Rule

If you liked it, you should have put a test on it. A refactor, a dependency bump, or an infra change is not responsible for catching your bug — your test is. If a change breaks behavior you had no test for, that's on you.

## Writing Good Tests

### Test State, Not Interactions
Assert on the *outcome*, not on which internal methods were called. Interaction tests break on every refactor even when behavior is unchanged.

```rust
// Good: asserts the outcome
#[test]
fn lists_tasks_newest_first() {
    let tasks = list_tasks(SortBy::CreatedAt, Order::Desc);
    assert!(tasks[0].created_at >= tasks[1].created_at);
}
// Bad: asserting "called db.query with ORDER BY created_at DESC" — tests the how, not the what.
```

### DAMP Over DRY in Tests
Production code favors DRY; tests favor **DAMP** (Descriptive And Meaningful Phrases). A test should read like a spec without the reader tracing shared helpers. Duplication is fine when it makes each test independently understandable.

### Prefer Real Implementations Over Mocks
```
Most → least confidence:
1. Real implementation  → catches real bugs
2. Fake                 → in-memory version (e.g. in-memory store)
3. Stub                 → canned return, no behavior
4. Mock (interaction)   → verifies calls — use sparingly, only at boundaries
```
Mock only where the real dependency is slow, non-deterministic, or has side effects you can't control (an external API, an email send). On-chain, prefer a real local validator over mocking the runtime — the mock is where the exploit hides. Over-mocking yields tests that pass while production breaks.

### Arrange-Act-Assert
```python
def test_marks_overdue_when_deadline_passed():
    task = create_task(title="Test", deadline=datetime(2026, 1, 1))  # Arrange
    result = check_overdue(task, now=datetime(2026, 1, 2))           # Act
    assert result.is_overdue is True                                 # Assert
```
Control the clock — pass `now` in; never let a unit test read the real wall clock.

### One Assertion Per Concept & Descriptive Names
Split "validates titles correctly" into `rejects_empty_titles`, `trims_whitespace`, `enforces_max_length`. Names should read like a specification (`throws_not_found_for_missing_task`), never `works` / `test_3`.

## Test Anti-Patterns to Avoid

| Anti-Pattern | Problem | Fix |
|---|---|---|
| Testing implementation details | Breaks on refactor though behavior is unchanged | Test inputs and outputs |
| Flaky tests (timing, order, wall clock) | Erode trust in the suite | Deterministic assertions; inject the clock; isolate state |
| Testing framework/library code | Wastes effort on third-party behavior | Test only YOUR code |
| Snapshot abuse | Huge snapshots nobody reviews | Use sparingly; review every change |
| No test isolation | Pass alone, fail together | Each test sets up and tears down its own state |
| Mocking everything | Pass while production breaks | Real > fake > stub > mock; mock only at slow/non-deterministic boundaries |
| Only the happy path (on-chain) | Ships an exploitable program | Test every rejected constraint: signer, PDA, owner, funds |
| `#[allow]` / `# noqa` / eslint-disable to green the suite | Hides the real failure | Fix the code; suppress only with a one-line justification |

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll write tests after the code works" | You won't. And after-the-fact tests test implementation, not behavior. |
| "This is too simple to test" | Simple code gets complicated. The test documents the expected behavior. |
| "Tests slow me down" | They slow you now and speed up every future change. Velocity is small correct increments, not skipped gates. |
| "I tested it manually" / "I sent one tx on devnet" | Manual checks don't persist. Tomorrow's change breaks it silently. Encode it as a test. |
| "cargo check / tsc passed" | Types prove shape, not behavior. A green compiler is not a green suite. |
| "The happy path works, ship the program" | On-chain, the failure paths ARE the security model. Untested rejection = untested defense. |
| "It's just a prototype" | Prototypes become production. Tests from day one prevent the test-debt crisis. |
| "Let me run the tests again to be extra sure" | After a clean run on unchanged code, rerunning adds nothing. Run again only after an edit. |

## Red Flags

- Writing code with no corresponding test
- A test that passes on its very first run (it may test nothing)
- "All tests pass" when no test command was actually run
- A bug fix with no failing-first reproduction test
- On-chain code that tests only the happy path — no bad-signer / wrong-PDA / wrong-owner cases
- Tests that assert internal call sequences instead of outcomes
- A unit test that needs a validator, RPC, DB, or network — it belongs in integration
- Skipping or disabling tests to make the suite green
- Rerunning the same test command with no intervening code change

## Verification

After completing any implementation:

- [ ] Every new behavior has a corresponding test
- [ ] Bug fixes include a reproduction test that failed before the fix, passes after
- [ ] Unit tests are hermetic (no network/DB/validator/wall clock) and green — real command output pasted, not assumed
- [ ] On-chain failure cases tested: bad signer, wrong PDA/seeds/bump, wrong `owner`/`has_one`, insufficient funds/rent
- [ ] Integration / `anchor test` / `pnpm e2e` run for anything crossing a real boundary
- [ ] Test names describe the behavior verified; none skipped or disabled
- [ ] New-code coverage aims >80% (per the DoD)
- [ ] Then run the full Definition of Done gate (`fullstack-standard` → `references/definition-of-done.md`)

**Note:** Run each test command after a change that could affect the result. After a clean run on unchanged code, don't repeat it — re-running adds no confidence.

## See Also

- `fullstack-standard` — the engineering bar; `references/definition-of-done.md` for the full gate and per-stack commands; `references/backend-standards.md` for Anchor/on-chain constraint rules.
- `source-driven-development` — verify a framework's testing API against its official docs before you write against it.
- `doubt-driven-development` — TDD's RED step is doubt made concrete; a failing test is a disproof attempt for a behavioral claim.
- `debugging-and-error-recovery` — when a reproduction test surfaces a failure, drop in to localize and fix.
