---
name: code-review-and-quality
description: Conducts multi-axis code review against the eonedge standard. Use before merging any change on this stack — Rust/Anchor/Solana, TypeScript, Astro/Next, Python. Use when reviewing code written by yourself, another agent, or a human. Use when you need to assess correctness, readability, architecture, security, and performance before code enters the main branch. Calls out over-abstraction, stringly-typed boundaries, and complexity that was relocated rather than removed.
---

# Code Review and Quality

## Overview

Every change gets reviewed before merge — no exceptions, including your own and other agents' code. The review evaluates five axes: correctness, readability, architecture, security, and performance. It is not a vibe check; it is the quality gate, and its exit bar is this workspace's **Definition of Done** (`fullstack-standard` → `references/definition-of-done.md`).

**The approval standard:** approve when the change definitely improves overall code health and passes the gate — even if it isn't exactly how you'd have written it. Perfect code doesn't exist; continuous improvement does. But two things are never "close enough" here: **over-abstraction** (a layer that doesn't earn its keep) and **stringly-typed boundaries** (an `any`, an untyped dict, a string where a domain type belongs). Those violate the house philosophy — flag them every time. **Relocating complexity isn't reducing it; making illegal states unrepresentable is.**

## When to Use

- Before merging any PR or change
- After finishing a feature implementation
- When another agent or model produced code you must evaluate
- When refactoring existing code
- After any bug fix — review both the fix and its regression test (see `debugging-and-error-recovery`)

## The Five-Axis Review

Every review runs all five axes. Lead with the ones that carry the most leverage.

### 1. Correctness

Does the code do what it claims?

- Does it match the spec / task?
- Edge cases handled (null/None, empty, boundary, zero-amount, overflow)?
- Error paths handled, not just the happy path?
- **Rust:** are `Result`s propagated with `?` and errors typed (`thiserror`)? Any `unwrap()`/`expect()` in a runtime path is a correctness bug unless a comment proves the invariant.
- **Anchor/on-chain:** is **every** account constraint present and checked — `has_one`, `seeds`, `bump`, `owner`, signer? Is client input treated as hostile? Are rent, CPI, and signer/authority checks explicit? **Do the tests cover failure cases (wrong PDA, bad signer, insufficient funds), not just the happy path?**
- Does it pass all tests, and do the tests assert the right behavior?
- Off-by-one, race conditions (Tokio tasks, concurrent tx), state inconsistencies?

### 2. Readability & Simplicity

Can another engineer or agent understand this without the author explaining it?

- Descriptive names consistent with the file's conventions? (No bare `data`, `tmp`, `result`, `x`.)
- Straightforward control flow (no nested ternaries, no deep `if` pyramids, guard clauses instead)?
- **Could this be done with less?** 1000 lines where 100 suffice is a failure. Fewer *concepts*, not just fewer lines.
- **Is every abstraction earning its complexity?** The house rule: no service layer, repository pattern, DI container, wrapper, or trait indirection unless the code is genuinely simpler *with* it. If the author can't justify a layer in one sentence, it's over-abstraction — flag it and propose the direct path (map the request straight to the handler; hit `sqlx` directly).
- Comments explain **why**, not what? Delete comments that narrate obvious code.
- Dead code, no-op variables, commented-out blocks, backwards-compat shims left behind? Git remembers — delete them.
- **A new conditional bolted onto an unrelated flow** is a design smell, not a nit — push it into its own helper/state/policy.
- **Repeated conditionals on the same shape** signal a missing model or dispatcher. A "temporary" branch is usually permanent debt.

### 3. Architecture

Does the change fit the system's design and the minimal-abstraction philosophy?

- Follows existing patterns, or introduces a new one? If new, is it justified in one sentence?
- Clean module boundaries; dependencies flow one direction (no cycles)?
- **Stringly-typed boundary?** A string, `any`, `unknown`, untyped Python dict, or gratuitous cast crossing a module boundary is a direct philosophy violation. Domain types are the contract — define them once (shared `*-types` crate / shared TS module) and depend on them. **The backend exports the API types; the frontend imports them and never redefines API shapes client-side.** Making the boundary explicit usually makes the surrounding branching disappear.
- Duplication that should be a shared canonical helper — or, conversely, a bespoke near-duplicate of a helper that already exists?
- Appropriate abstraction level: not over-engineered, not too coupled?
- **Does this refactor reduce complexity or just relocate it?** Count the concepts a reader must hold. If a "cleaner" version leaves that count unchanged, it isn't cleaner. Prefer the restructuring that makes whole branches/modes/layers *disappear* over one that re-centralizes the same logic. Prefer deleting an abstraction to polishing it.
- **Feature-specific logic leaking into a shared/general-purpose module?** Keep logic in its owning layer; don't normalize architectural drift.

### 4. Security

For the full standard, see `fullstack-standard` (Security & secrets hygiene) and `references/backend-standards.md`. Does the change introduce risk?

- **Secrets:** no keys, tokens, seed phrases, or `.env` material in code, logs, or the diff — read the env, never a literal. **Nothing sensitive shipped to the browser** (client code is public; public keys/endpoints only).
- **On-chain:** untrusted client accounts validated via constraints and PDA derivation? No authority a malicious signer could assume? Arithmetic checked (no silent overflow on lamport/token math)?
- Input validated and sanitized at the boundary?
- SQL via parameterized `sqlx` queries — never string concatenation?
- Outputs encoded to prevent XSS (frontend)? Auth/authorization checked where needed?
- External data (APIs, RPC responses, logs, config, user content) treated as untrusted before use in logic or rendering?

### 5. Performance

Does the change introduce a performance problem?

- N+1 query patterns? Unbounded loops or unconstrained fetching? Missing pagination on list endpoints?
- Blocking the Tokio runtime with sync work that should be `async`?
- **On-chain:** compute-unit blowups, unbounded account iteration, avoidable CPIs?
- **Frontend:** unnecessary client JS, unneeded `"use client"`, re-renders, large payloads, layout shift?
- Large objects allocated in hot paths?

## Structural Remedies

When you flag a structural problem, propose the move — don't just name the smell. Reach for a named restructuring:

- **Replace a chain of conditionals** with a typed model / enum match or an explicit dispatcher.
- **Collapse duplicate branches** into one clearer flow.
- **Separate orchestration from business logic** so each reads on its own.
- **Move feature-specific logic** out of a shared module into the crate/package that owns the concept.
- **Reuse the canonical helper** instead of a bespoke near-duplicate.
- **Make a type boundary explicit** (define the domain type; drop the `any`/string) so downstream branching disappears.
- **Delete a pass-through wrapper** or service layer that adds indirection without clarifying the API.
- **Extract a helper, or split a large file** into focused modules.

Prefer the remedy that removes moving pieces over one that spreads the same complexity around.

## Change Sizing

Small, focused changes review faster and deploy safer.

```
~100 lines changed   → Good. Reviewable in one sitting.
~300 lines changed   → Acceptable if it's one logical change.
~1000 lines changed  → Too large. Split it.
```

**Watch file size, not just diff size.** A small diff can still push a file past a healthy boundary (~1000 total lines is an inspection signal, not a hard cap). When a change materially grows an already-large file, extract helpers/modules **first**, then add. Decompose, then pile on.

**One change =** one self-contained modification addressing one thing, with its tests, leaving the system working. One slice of a feature — not the whole feature.

**Separate refactoring from feature work.** Refactor + new behavior in one change is two changes — submit them separately. Trivial renames can ride along at reviewer discretion.

**Splitting strategies:**

| Strategy | How | When |
|----------|-----|------|
| **Stack** | Merge a small change, base the next on it | Sequential dependencies |
| **By file group** | Split changes needing different context | Cross-cutting concerns |
| **Horizontal** | Land shared types/stubs first, then consumers | Layered (types crate → server → client) |
| **Vertical** | Thin full-stack slices of the feature | Feature work |

**Large changes are acceptable** for whole-file deletions and mechanical refactors where the reviewer verifies intent, not every line.

## Change Descriptions

Every change needs a **Conventional Commit** description that stands alone in history (`type(scope): summary` — `feat`, `fix`, `refactor`, `test`, `chore`, …; see `fullstack-standard` → Git discipline).

- **First line:** imperative, standalone, informative. `fix(vault): reject withdraw from non-authority signer`, not "fixing stuff."
- **Body:** what changes and *why* — context, decisions, and reasoning not visible in the diff. Link issues, benchmark numbers, or the tx signature you verified against. Acknowledge shortcomings honestly.
- **Anti-patterns:** "Fix bug," "Fix build," "Add patch," "Moving code from A to B," "Phase 1."

## Review Process

### Step 1: Understand the Context

Before reading code: what is this trying to accomplish, what spec/task does it implement, what behavior should change?

### Step 2: Review the Tests First

Tests reveal intent and coverage:

- Do tests exist for the change, and do they hit no network/DB (hermetic units), with integration/`anchor test`/`pytest tests/integration` kept separate?
- Do they test behavior, not implementation details? Descriptive names?
- Edge and **failure** cases covered (on-chain: wrong signer/PDA/funds)?
- Would they catch a regression if the code changed?

### Step 3: Review the Implementation

Walk each changed file with the five axes in mind: correctness → readability → architecture → security → performance.

### Step 4: Categorize Findings

Label every comment so the author knows what's required vs optional:

| Prefix | Meaning | Author action |
|--------|---------|---------------|
| *(no prefix)* | Required change | Address before merge |
| **Critical:** | Blocks merge | Security hole, fund loss, lost/corrupt on-chain state, broken functionality |
| **Nit:** | Minor, optional | May ignore — formatting, style |
| **Optional:** / **Consider:** | Suggestion | Worth considering, not required |
| **FYI** | Informational | No action — context for later |

**Lead with what matters.** Order by leverage: correctness and security first, then structural regressions and missed simplifications (over-abstraction, stringly-typed boundaries, relocated complexity), then everything else. A few high-conviction comments beat a long list. **If you have one structural problem and ten nits, the structural problem *is* the review.**

### Step 5: Verify the Verification

Check the author's verification story against the DoD gate: which real commands were run (`cargo clippy -- -D warnings`, `cargo test`, `anchor test`, `ruff check .`, `pytest`, `pnpm lint`, `pnpm tsc --noEmit`, `pnpm test`/`pnpm e2e`)? Did the build pass? Was the change driven end-to-end (tx on devnet, page loaded, endpoint hit) — not just typechecked? Screenshots for UI, before/after for perf?

## Multi-Agent Review Pattern

Different models have different blind spots — a second reviewer catches what the author missed:

```
Model A writes the code
    │
    ▼
Model B reviews for correctness, security, architecture (against this skill)
    │
    ▼
Model A addresses the feedback
    │
    ▼
You make the final call
```

**Example prompt for a review agent:**
```
Review this change against fullstack-standard (minimal abstraction, type-driven,
no unwrap/any/stringly-typed boundaries, on-chain constraints checked). Spec: [X].
Expected behavior: [Y]. Flag findings as Critical / Required / Optional / Nit.
```

## Dead Code Hygiene

After any refactor or implementation change, check for orphaned code, list it, and **ask before deleting** anything you're unsure about:

```
DEAD CODE IDENTIFIED:
- format_legacy_ts() in crates/util/src/time.rs — replaced by format_ts()
- OldVaultCard in web/components/ — replaced by VaultCard
- LEGACY_RPC_URL in config.ts — no remaining references
→ Safe to remove these?
```

Don't leave dead code lying around; don't silently delete something whose purpose you're not certain of.

## Handling Disagreements

1. **Technical facts and data** override opinions.
2. **The stack standard** (`fullstack-standard` and its references) is the authority on style and structure.
3. **Software design** is judged on engineering principles, not personal taste.
4. **Codebase consistency** wins where it doesn't degrade overall health.

**Don't accept "I'll clean it up later."** Deferred cleanup rarely happens; require it before merge unless it's a genuine emergency, in which case file a tracked issue with self-assignment.

## Honesty in Review

- **Don't rubber-stamp.** "LGTM" with no evidence of review helps no one.
- **Don't soften real issues.** "Might be a minor concern" about a fund-draining bug is dishonest.
- **Quantify.** "This N+1 adds ~50ms per item" beats "this could be slow."
- **Push back on flawed approaches and propose the alternative.** Sycophancy is a review failure mode.
- **Accept override gracefully.** If the author has full context and disagrees, defer. Comment on the code, not the person.

## Dependency Discipline

Every dependency is a liability. Before adding one:

1. Does the existing stack solve this? (Often yes — reach for std / an existing crate or util first.)
2. How large is it? (Bundle/binary impact.)
3. Actively maintained? (Last commit, open issues.)
4. Known vulnerabilities? (`cargo audit`, `pnpm audit`, `pip-audit`.)
5. License compatible?

**Rule:** prefer the standard library and existing utilities over a new dependency.

## The Review Checklist

```markdown
## Review: [change title]

### Context
- [ ] I understand what this change does and why

### Correctness
- [ ] Matches spec/task; edge and error paths handled
- [ ] Rust: errors typed via thiserror; no unwrap()/expect() in runtime paths
- [ ] On-chain: every constraint checked (has_one/seeds/bump/owner/signer); failure cases tested
- [ ] Tests cover the change adequately

### Readability
- [ ] Clear, consistent names; straightforward control flow
- [ ] No over-abstraction — every layer/wrapper earns its keep in one sentence
- [ ] No dead code or what-comments left behind

### Architecture
- [ ] Type-driven boundaries — no any/string/untyped dict crossing a module edge
- [ ] Frontend imports backend-exported types; no redefined API shapes
- [ ] Refactor reduces concepts, doesn't relocate them
- [ ] No feature logic in shared modules; no bespoke near-duplicate of a canonical helper
- [ ] File stays within a healthy size

### Security
- [ ] No secrets in code/logs/diff; nothing sensitive shipped to the browser
- [ ] Input validated at boundaries; sqlx parameterized; external data untrusted
- [ ] Auth/authority checks in place (on-chain and server)

### Performance
- [ ] No N+1 / unbounded fetching; pagination on lists; async not blocking the runtime
- [ ] No compute-unit or re-render blowups

### Verification
- [ ] Definition of Done gate is green (fullstack-standard → references/definition-of-done.md)
- [ ] Change driven end-to-end, not just typechecked

### Verdict
- [ ] **Approve** — ready to merge
- [ ] **Request changes** — issues must be addressed
```

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "It works, that's good enough" | Working code that's unreadable, over-abstracted, or insecure is debt that compounds. The gate is the bar, not "it runs." |
| "I wrote it, so I know it's correct" | Authors are blind to their own assumptions. Every change benefits from a second set of eyes. |
| "We'll clean it up later" | Later never comes. The review is the quality gate — require cleanup before merge. |
| "AI-generated code is probably fine" | AI code needs more scrutiny, not less. It's confident and plausible even when wrong. |
| "The tests pass, so it's good" | Tests don't catch over-abstraction, stringly-typed boundaries, or security holes. Necessary, not sufficient. |
| "The abstraction adds flexibility" | Flexibility you don't need now is complexity you pay for now. No layer until the code is simpler with it. |
| "A string is easier than defining a type" | A stringly-typed boundary pushes the cost onto every caller and every future reader. Define the domain type once. |
| "The refactor makes it cleaner" | Relocating complexity isn't reducing it. If the reader holds the same number of concepts, look for the version where branches disappear. |
| "It's only a small addition to this file" | Small diffs still bolt branches onto unrelated flows and grow files past a healthy size. Judge the resulting structure. |

## Red Flags

- PRs merged with no review
- Review that only checks whether tests pass (ignores the other four axes)
- "LGTM" without evidence of actual review
- Security- or fund-sensitive on-chain changes without a security-focused pass
- An Anchor change whose tests only cover the happy path
- Large PRs "too big to review properly" (split them)
- No regression test with a bug-fix PR
- Comments without severity labels
- Accepting "I'll fix it later"
- **A new layer, wrapper, or service that isn't justified in one sentence** (over-abstraction)
- **An `any`, cast, string, or untyped dict crossing a module boundary** (stringly-typed)
- A refactor that moves code around without cutting the concept count
- A change growing an already-large file instead of decomposing it
- New conditionals scattered into unrelated code paths (a missing abstraction)
- Feature logic placed in a shared module, or a bespoke duplicate of a canonical helper

## Verification

After the review is complete:

- [ ] All Critical issues resolved
- [ ] All Required (no-prefix) changes resolved or explicitly deferred with justification
- [ ] Over-abstraction and stringly-typed boundaries surfaced with a proposed remedy
- [ ] Definition of Done gate is green (`fullstack-standard` → `references/definition-of-done.md`)
- [ ] Verification story documented (what changed, which real commands ran, how it was driven end-to-end)

**Presumptive blockers** — surface each and propose the simpler design; escalate to Required when the change actively makes structure worse: a refactor that relocates complexity; a file pushed past the size boundary with no decomposition; feature logic in a shared module; a near-duplicate of a canonical helper; a silent fallback or stringly-typed boundary that hides an unclear invariant; an over-abstraction with no one-sentence justification.

## See Also

- `fullstack-standard` — the philosophy and the Definition of Done that is this review's exit bar.
- `code-simplification` — the toolkit for the structural remedies you'll propose.
- `debugging-and-error-recovery` — when the review finds a real bug, or to review a fix + its regression test.
