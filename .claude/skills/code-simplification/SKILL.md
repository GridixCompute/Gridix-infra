---
name: code-simplification
description: Simplifies code for clarity without changing behavior, on the eonedge stack — Rust/Anchor/Solana, TypeScript, Astro/Next, Python. Use when refactoring for readability, when code works but is harder to read, maintain, or extend than it should be, or when reviewing code that has accumulated complexity. Anchored in minimal abstraction, Chesterton's Fence, and the rule that relocating complexity isn't reducing it.
---

# Code Simplification

## Overview

Simplify code by reducing complexity while preserving exact behavior. The goal is not fewer lines — it's code a new contributor understands faster. Every simplification passes one test: "Would someone new to this repo grasp this quicker than the original?" This is the minimal-abstraction philosophy applied after the fact: layers must earn their keep, domain types are the contract, and **the repo is the source of truth**. Above all — **relocating complexity isn't reducing it. If the reader still holds the same number of concepts, you changed nothing worth changing.**

## When to Use

- A feature works and tests pass, but the implementation feels heavier than it needs to be
- Code review flagged readability or complexity (see `code-review-and-quality`)
- You hit deeply nested logic, long functions, or unclear names
- Refactoring code written under time pressure
- Consolidating related logic scattered across files
- Cleaning up duplication or inconsistency after a merge

**When NOT to use:**

- Code is already clean — don't simplify for its own sake
- You don't yet understand what the code does — comprehend before you touch (Chesterton's Fence)
- The code is performance-critical (a hot Tokio path, an on-chain compute-unit budget) and the "simpler" version is measurably slower or costs more CUs
- You're about to rewrite the module entirely — polishing throwaway code wastes effort

## The Five Principles

### 1. Preserve Behavior Exactly

Change only *how* the code expresses itself, never *what* it does. Inputs, outputs, side effects, error behavior, edge cases, and — for on-chain code — the exact accounts, constraints, and instruction semantics must stay identical. If you're unsure a change preserves behavior, don't make it.

```
ASK BEFORE EVERY CHANGE:
→ Same output for every input?
→ Same error behavior (same typed error variant, same revert / error code)?
→ Same side effects and ordering (same CPIs, same account mutations)?
→ Do all existing tests still pass without modification?
```

### 2. Follow Project Conventions

Simplification means making code more consistent with **this** codebase, not imposing outside preferences. Before touching anything:

```
1. Read the repo's conventions and the fullstack-standard skill
2. Study how neighboring code handles the same pattern
3. Match the file's existing style for:
   - Rust: error handling (thiserror + ?), module layout, trait use
   - TS: import ordering, strict-mode idioms, how API types are imported
   - Python: ruff formatting, type-hint depth, loguru usage
   - On-chain: how PDAs are derived and constraints are declared elsewhere
```

Simplification that breaks project consistency isn't simplification — it's churn.

### 3. Prefer Clarity Over Cleverness — and Minimal Abstraction

Explicit beats compact whenever the compact version needs a mental pause to parse. And this is where the house philosophy bites hardest: **the simplest form is usually the direct one — no wrapper, no service layer, no indirection that doesn't earn its keep.**

```rust
// UNCLEAR: dense nested match, hard to scan
let label = match (item.is_new, item.is_archived) {
    (true, _) => "New", (_, true) => "Archived", _ => "Active",
};

// CLEAR: guard clauses read top to bottom
fn status_label(item: &Item) -> &'static str {
    if item.is_new { return "New"; }
    if item.is_archived { return "Archived"; }
    "Active"
}
```

Prefer the direct path over ceremony:

```rust
// OVER-ABSTRACTED: a repository wrapping a single sqlx call
struct UserRepository { pool: PgPool }
impl UserRepository {
    async fn find(&self, id: Uuid) -> Result<User, DbError> {
        sqlx::query_as!(User, "SELECT * FROM users WHERE id = $1", id)
            .fetch_one(&self.pool).await.map_err(Into::into)
    }
}

// SIMPLER: call sqlx directly at the handler. Delete the layer that added nothing.
async fn find_user(pool: &PgPool, id: Uuid) -> Result<User, DbError> {
    Ok(sqlx::query_as!(User, "SELECT * FROM users WHERE id = $1", id)
        .fetch_one(pool).await?)
}
```

### 4. Maintain Balance

Simplification has a failure mode: over-simplification. Watch for these traps:

- **Inlining too aggressively** — removing a helper that gave a concept a name makes the call site harder to read. A well-named function is an abstraction that *earns* its keep.
- **Combining unrelated logic** — two simple functions merged into one branchy function is not simpler.
- **Removing "unnecessary" abstraction that was load-bearing** — some layers exist for a real reason (a genuine second implementation, a testability seam). Distinguish those from ceremony.
- **Weakening the type boundary** — collapsing a domain type down to a string or an `any` to "simplify" is the opposite of the house standard. Types are the contract; keep them.
- **Optimizing for line count** — fewer lines is not the goal; faster comprehension and fewer concepts are.

### 5. Scope to What Changed

Default to simplifying recently modified code. Avoid drive-by refactors of unrelated code unless explicitly asked. Unscoped simplification makes noisy diffs and risks regressions in code you didn't mean to touch. **Separate the simplification change from any feature or bug-fix change** — mixed changes are harder to review and revert (see `code-review-and-quality` → Change Sizing).

## The Simplification Process

### Step 1: Understand Before Touching (Chesterton's Fence)

Before changing or removing anything, understand why it exists. If a fence stands across a road and you don't know why, don't tear it down — first learn the reason, then decide whether it still applies.

```
BEFORE SIMPLIFYING, ANSWER:
- What is this code's responsibility?
- What calls it? What does it call?
- What are the edge cases and error paths?
- Do tests define its expected behavior?
- Why might it have been written this way?
  (Performance? A compute-unit budget? A signer/rent constraint? A platform quirk?)
- git blame: what was the original context?
```

On-chain code raises the stakes: a constraint or an extra account check that *looks* redundant may be the thing stopping a malicious signer. **Never simplify away an Anchor constraint (`has_one`, `seeds`, `bump`, `owner`, signer) or an authority check to reduce lines** — that's removing a security control, not simplifying. If you can't answer the questions above, read more context first.

### Step 2: Identify Simplification Opportunities

Scan for these signals — each is concrete, not a vague smell:

**Structural complexity:**

| Pattern | Signal | Simplification |
|---------|--------|----------------|
| Deep nesting (3+ levels) | Hard to follow control flow | Guard clauses / early returns (or `?` in Rust) |
| Long functions (50+ lines) | Multiple responsibilities | Split into focused, well-named functions |
| Nested ternaries / match arms | Needs a mental stack to parse | if/else chain, `match` on an enum, or lookup map |
| Boolean parameter flags | `do_thing(true, false, true)` | Options struct or separate functions |
| Repeated conditionals | Same check in many places | Extract a well-named predicate |
| **Gratuitous layer/wrapper** | Repo/service/DI wrapping one call | Inline it; call the underlying API directly |

**Naming and readability:**

| Pattern | Signal | Simplification |
|---------|--------|----------------|
| Generic names | `data`, `result`, `tmp`, `val` | Rename to the content: `user_profile`, `validation_errors` |
| Abbreviated names | `usr`, `cfg`, `btn` | Full words unless universal (`id`, `url`, `pda`) |
| Misleading names | `get` that also mutates | Rename to reflect real behavior |
| Comments narrating "what" | `// increment counter` over `count += 1` | Delete — the code is clear |
| Comments explaining "why" | `// retry: RPC is flaky under load` | Keep — carries intent the code can't |

**Redundancy:**

| Pattern | Signal | Simplification |
|---------|--------|----------------|
| Duplicated logic | Same 5+ lines in several places | Extract a shared canonical helper |
| Dead code | Unreachable branches, unused vars, commented-out blocks | Remove (after confirming it's dead) |
| Unnecessary abstraction | Wrapper/trait that adds no value | Inline; use the direct path |
| Over-engineered pattern | Factory-for-a-factory, strategy-with-one-strategy | Replace with the direct approach |
| Redundant type ceremony | Cast to an already-inferred type; `as` where the type flows | Remove it |

### Step 3: Apply Changes Incrementally

One simplification at a time; run the relevant tests after each.

```
FOR EACH SIMPLIFICATION:
1. Make the one change
2. Run tests: cargo test · pytest · pnpm test  (anchor test if on-chain)
3. Pass → continue to the next (or commit)
4. Fail → revert and reconsider (a failing test may mean you changed behavior)
```

Don't batch many simplifications into one untested change — if something breaks you won't know which move caused it.

**The Rule of 500:** if a refactor would touch more than ~500 lines, invest in automation (a codemod, `cargo fix`, a scripted AST transform) rather than editing by hand. Manual edits at that scale are error-prone and exhausting to review.

### Step 4: Verify the Result

Step back and evaluate the whole:

```
COMPARE BEFORE AND AFTER:
- Genuinely easier to understand? Fewer concepts to hold, not just fewer lines?
- Any new pattern inconsistent with the codebase?
- Clean, reviewable diff, scoped to what changed?
- Would a teammate approve this as a net improvement?
```

If the "simplified" version is harder to follow or review, revert. Not every attempt succeeds. Then run the layer's Definition of Done gate.

## Language-Specific Guidance

### Rust

```rust
// SIMPLIFY: match-on-Result boilerplate → the ? operator
// Before
let user = match find_user(pool, id).await {
    Ok(u) => u,
    Err(e) => return Err(e),
};
// After
let user = find_user(pool, id).await?;

// SIMPLIFY: manual collection loop → iterator (keeps behavior, sheds ceremony)
// Before
let mut active = Vec::new();
for u in users {
    if u.is_active { active.push(u); }
}
// After
let active: Vec<_> = users.into_iter().filter(|u| u.is_active).collect();

// DO NOT "simplify" an error away:
//   let user = find_user(pool, id).await.unwrap();  // ← removes the typed error, a regression
```

### Python

```python
# SIMPLIFY: verbose dict building → comprehension
# Before
result = {}
for item in items:
    result[item.id] = item.name
# After
result = {item.id: item.name for item in items}

# SIMPLIFY: nested conditionals → guard clauses (early raise)
# Before
def process(data):
    if data is not None:
        if data.is_valid():
            return do_work(data)
        else:
            raise ValueError("invalid data")
    else:
        raise TypeError("data is None")
# After
def process(data: Data) -> Result:
    if data is None:
        raise TypeError("data is None")
    if not data.is_valid():
        raise ValueError("invalid data")
    return do_work(data)
# (Keep type hints and loguru logging — simplification never strips them.)
```

### TypeScript / Astro / Next

```typescript
// SIMPLIFY: redundant async wrapper
// Before
async function getUser(id: string): Promise<User> {
  return await userService.findById(id);
}
// After
function getUser(id: string): Promise<User> {
  return userService.findById(id);
}

// SIMPLIFY: verbose conditional assignment
// Before
let displayName: string;
if (user.nickname) { displayName = user.nickname; }
else { displayName = user.fullName; }
// After
const displayName = user.nickname || user.fullName;

// DO NOT weaken the type boundary to "simplify":
//   function getUser(id: string): Promise<any>   // ← violates strict/type-driven design
```

```tsx
// Astro/Next: prefer removing client JS over restructuring it.
// If a component doesn't need interactivity, dropping "use client" (Next) or an
// island directive (Astro) is the highest-value simplification: less shipped JS.
// Prop-drilling → context is a judgment call — flag it, don't auto-refactor.
```

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "It's working, no need to touch it" | Working code that's hard to read is hard to fix when it breaks. Simplifying now pays off on every future change. |
| "Fewer lines is always simpler" | A one-line nested ternary isn't simpler than a 5-line guard chain. Simplicity is comprehension speed and concept count, not line count. |
| "I'll just quickly simplify this unrelated code too" | Unscoped simplification makes noisy diffs and risks regressions in code you didn't mean to touch. Stay scoped. |
| "The types make it self-documenting" | Types document structure, not intent. A well-named function explains *why*; keep it — don't inline it away. |
| "This abstraction might be useful later" | Don't preserve speculative abstractions. Unused now = complexity without value. Delete it; re-add when a real second use arrives. |
| "The original author must have had a reason" | Maybe — check git blame (Chesterton's Fence). But accumulated complexity often has no reason; it's the residue of iteration under pressure. |
| "This refactor makes it cleaner" | If the reader still holds the same number of concepts, you relocated complexity, not reduced it. Look for the version where branches disappear. |
| "I'll simplify while adding this feature" | Separate refactoring from feature work. Mixed changes are harder to review, revert, and read in history. |

## Red Flags

- Simplification that requires modifying tests to pass (you likely changed behavior)
- "Simplified" code that's longer or harder to follow than the original
- Renaming to your preference rather than the file's conventions
- Removing error handling — or replacing a typed `Result` with `unwrap()`/`unwrap_or_default()` — to "clean it up"
- Collapsing a domain type into a string / `any` / untyped dict to shed lines
- **Simplifying away an Anchor constraint, signer, or authority check** (that's removing a security control)
- Simplifying code you don't fully understand
- Batching many simplifications into one hard-to-review commit
- Refactoring outside the current task's scope without being asked
- A "simpler" version that relocates complexity instead of removing it

## Verification

After a simplification pass:

- [ ] All existing tests pass **without modification** (`cargo test` · `pytest` · `pnpm test` · `anchor test` as applicable)
- [ ] Behavior identical — same outputs, errors, side effects, on-chain semantics
- [ ] Lint/format clean, no new warnings (`cargo clippy -- -D warnings` · `ruff check .` · `pnpm lint`; `cargo fmt` / `ruff format` / `prettier`)
- [ ] No error handling removed or weakened; no typed error turned into an `unwrap`
- [ ] No type boundary weakened (no new `any`/string-for-a-type/untyped dict); no security constraint dropped
- [ ] Each simplification is a reviewable, incremental change, scoped to what changed
- [ ] The diff is clean — no unrelated changes, no feature work mixed in
- [ ] The result genuinely reduces the concepts a reader must hold — a teammate would approve it as a net improvement
- [ ] Definition of Done gate is green (`fullstack-standard` → `references/definition-of-done.md`)

## See Also

- `fullstack-standard` — the minimal-abstraction, type-driven philosophy this skill enforces, and the DoD gate.
- `code-review-and-quality` — where simplification opportunities get flagged; this skill supplies the structural remedies.
- `debugging-and-error-recovery` — if a "simplification" breaks a test, stop and debug the behavior change before continuing.
