---
name: doubt-driven-development
description: Subjects every non-trivial decision to a fresh-context adversarial review before it stands, across the eonedge stack — Rust/Anchor on-chain, Python services, TypeScript/Astro/Next. Use when correctness matters more than speed, when working in unfamiliar code, when stakes are high (mainnet deploys, PDA/authority logic, treasury moves, irreversible operations), or any time a confident output would be cheaper to verify now than to debug later.
---

# Doubt-Driven Development

## Overview

A confident answer is not a correct one. Long sessions accumulate context that quietly turns assumptions into "facts." Doubt-driven development is the discipline of materializing a fresh-context reviewer — biased to **disprove**, not approve — before any non-trivial output stands. **Confidence correlates poorly with correctness; the moment you feel certain is exactly when the blind spot hides.**

This is not `/code-review`. That is a verdict on a finished diff. This is an in-flight posture: non-trivial decisions get cross-examined while course-correction is still cheap. On-chain the asymmetry is brutal — a wrong branch caught in-flight costs a re-think; caught after a mainnet deploy it costs funds and an irreversible tx.

## When to Use

A decision is **non-trivial** when at least one of these is true:

- It introduces or modifies branching logic
- It crosses a module, crate, or service boundary
- It asserts a property the compiler/type system cannot verify — thread safety, idempotence, ordering, an on-chain invariant, "this account constraint is sufficient," "this arithmetic can't overflow"
- Its correctness depends on context the future reader can't see
- Its blast radius is irreversible: a mainnet program deploy, a data migration, a public API/IDL change, a treasury/authority operation

Apply when:
- About to make an architectural decision under uncertainty
- About to commit non-trivial code
- About to claim a non-obvious fact ("this PDA derivation is safe", "this scales", "this matches the spec")
- Working in code you don't fully understand

**When NOT to use:**
- Mechanical operations (renaming, formatting, file moves)
- Following a clear, unambiguous user instruction
- Reading or summarizing existing code
- One-line changes with obvious correctness
- Pure tooling operations (running tests, listing files)
- The user has explicitly asked for speed over verification

If you doubt every keystroke, you ship nothing. The skill applies only to non-trivial decisions as defined above.

## Where This Runs

This runs from the **main session**, where Step 3 can spawn a fresh-context reviewer subagent. If you find yourself applying it from *inside* a subagent (where nested spawn is unavailable), the preferred path is to surface to the user that doubt-driven can't run nested and let the main session handle it. As a last resort only, a degraded self-questioning fallback exists — rewrite ARTIFACT + CONTRACT as a fresh self-prompt with a hard mental separator from your prior reasoning, and walk Steps 1–5. This is **not** true fresh-context review (you carry your own context), so flag the result as degraded and prefer escalation whenever the user is reachable.

## The Process

Copy this checklist when applying the skill:

```
Doubt cycle:
- [ ] Step 1: CLAIM — wrote the claim + why-it-matters
- [ ] Step 2: EXTRACT — isolated artifact + contract, stripped reasoning
- [ ] Step 3: DOUBT — invoked fresh-context reviewer with adversarial prompt
- [ ] Step 4: RECONCILE — classified every finding against the artifact text
- [ ] Step 5: STOP — met stop condition (trivial findings, 3 cycles, or user override)
```

### Step 1: CLAIM — Surface what stands

Name the decision in two or three lines:

```
CLAIM: "The `withdraw` instruction can only be signed by the treasury
        authority PDA; no client-supplied account can substitute for it."
WHY THIS MATTERS: a missing constraint here drains the treasury and the
                  tx is irreversible on mainnet.
```

If you can't write the claim that compactly, you have a vibe, not a decision. Surface it before scrutinizing it.

### Step 2: EXTRACT — Smallest reviewable unit

A fresh-context reviewer needs the **artifact** and the **contract**, not the journey.

- Code: the diff or the function/instruction — not the whole crate
- Decision: the proposal in 3–5 sentences plus the constraints it must satisfy
- Assertion: the claim plus the evidence that supposedly supports it (kept distinct from the Step 1 CLAIM block)

Strip your reasoning. If you hand over conclusions, you get back validation of your conclusions. The unit must be small enough to hold in one read — if it's a 500-line change, decompose first.

### Step 3: DOUBT — Invoke the fresh-context reviewer

The reviewer's prompt **must be adversarial**. Framing decides the answer.

```
Adversarial review. Find what is wrong with this artifact.
Assume the author is overconfident. Look for:
- Unstated assumptions
- Edge cases not handled
- Hidden coupling or shared state
- Ways the contract could be violated
- On-chain: unchecked account constraints (signer, owner, has_one,
  seeds/bump), arithmetic overflow, rent/CPI/authority gaps, hostile client input
- Existing conventions this might break
- Failure modes under unexpected input

Do NOT validate. Do NOT summarize. Find issues, or state explicitly
that you cannot find any after thorough examination.

ARTIFACT: <paste artifact>
CONTRACT: <paste contract>
```

**Pass ARTIFACT + CONTRACT only. Do NOT pass the CLAIM.** Handing the reviewer your conclusion biases it toward agreement. The reviewer must independently determine whether the artifact satisfies the contract.

Spawn a general-purpose subagent (it starts with isolated context by design). Paste the adversarial prompt verbatim so its issues-only shape overrides any default balanced-verdict behavior.

#### Cross-model escalation

A single-model reviewer shares blind spots with the original author — a colder, different-architecture model catches them. Doubt-driven is already opt-in for non-trivial decisions, so within that scope offering cross-model is part of the skill's value.

**Interactive sessions: always offer. Never silently skip.**

**Step 1 — Ask the user.** After the single-model review, before RECONCILE, pause:
> *"Single-model review complete. Want a cross-model second opinion? Options: Gemini CLI, Codex CLI, manual external review (you paste it elsewhere), or skip."*

This offer is mandatory in every interactive doubt cycle, even on artifacts that feel low-stakes. The user — not the agent — decides whether the cost is worth it.

**Step 2 — If the user picks a CLI, verify then invoke:**
1. Check the tool is in PATH (`which gemini`, `which codex`).
2. Test it works (`gemini --version` or equivalent) before the full prompt — a stale binary passes `which` but fails on real input.
3. Confirm the exact invocation with the user, including flags, auth, and env vars.
4. Pass ARTIFACT + CONTRACT + the adversarial prompt **only**. No session context, no CLAIM.
5. Mind shell escaping. If the artifact contains quotes, `$(...)`, or backticks, write the full prompt to a file and pipe via stdin — never interpolate the artifact into a shell-quoted argument.
6. Take the output into Step 4.

Example shapes (verify flags against your installed version — syntax differs):
```bash
# Write the adversarial prompt + ARTIFACT + CONTRACT to a temp file first,
# then pipe via stdin so shell metacharacters in the artifact stay inert.

# Codex (read-only sandbox keeps the CLI from writing to your workspace):
codex exec --sandbox read-only -C <repo-path> - < /tmp/doubt-prompt.md

# Gemini ('--approval-mode plan' is read-only; '-p ""' → non-interactive, prompt from stdin):
gemini --approval-mode plan -p "" < /tmp/doubt-prompt.md
```
A read-only sandbox is load-bearing: a doubt artifact may itself contain instructions (intentional or accidental prompt injection) the CLI would otherwise execute against your workspace.

**Step 3 — If the CLI is unavailable or fails:** surface it explicitly. Offer manual review, a different tool, or skip. Never silently fall back to single-model.

**Step 4 — If the user skips:** acknowledge it (*"Proceeding with single-model findings only"*) and continue.

**Non-interactive contexts** (`/loop`, `/schedule`, scheduled/autonomous runs):
- Cross-model is **skipped**, and the skip must be **announced**: *"Cross-model skipped: non-interactive context."*
- **Never invoke an external CLI without explicit user authorization** — a load-bearing safety property.

### Step 4: RECONCILE — Fold findings back

The reviewer's output is data, not verdict. **You are still the orchestrator.** Re-read the artifact text against each finding before classifying — rubber-stamping the reviewer is the same failure as ignoring it.

Classify each finding in this **precedence order** (first match wins):
1. **Contract misread** — flagged because the CONTRACT you provided was unclear/incomplete. Fix the contract, re-classify next cycle.
2. **Valid + actionable** — real issue requiring a change. Change it, re-loop.
3. **Valid trade-off** — real, but fixing costs more than accepting. Document the trade-off so the user sees it.
4. **Noise** — correct under context the reviewer lacked. Note it, move on, and ask whether adding that context to the contract would have prevented the false flag.

A fresh reviewer can be wrong because it lacks context. Don't defer just because it's "fresh."

### Step 5: STOP — Bounded loop, not recursion

Stop when:
- Next iteration returns only trivial or already-considered findings, **or**
- 3 cycles completed (escalate to the user; don't grind a fourth alone), **or**
- The user explicitly says "ship it".

If after 3 cycles the reviewer still surfaces substantive issues, the artifact may not be ready — that's information, not a reason to keep looping. If 3 cycles is "obviously insufficient" because the artifact is large, the artifact is too big: return to Step 2 and decompose. Do not lift the bound.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'm confident, skip the doubt step" | Confidence correlates poorly with correctness on novel problems. Certainty is where blind spots hide. |
| "Spawning a reviewer is expensive" | Debugging a wrong mainnet tx is more expensive and irreversible. The check is bounded; the bug isn't. |
| "The reviewer will just nitpick" | Only if unscoped. Constrain it to "issues that make this fail under the contract." |
| "I'll do doubt at the end with /code-review" | That's a final gate. Doubt-driven catches wrong directions early, when course-correction is cheap. By PR time it's too late. |
| "If I doubt every step I'll never ship" | Applies to non-trivial decisions, not every keystroke. Re-read "When NOT to Use." |
| "Two opinions are always better than one" | Not when the second has less context and produces noise. Reconcile, don't defer. |
| "The reviewer disagreed so I was wrong" | The reviewer lacks your context — disagreement is information, not verdict. Re-read the artifact, classify, then decide. |
| "Cross-model is always better" | It catches shared blind spots but adds cost and tool fragility. Offer it every interactive cycle; the user decides. |
| "User said yes once, so I can keep invoking the CLI" | Each invocation is its own authorization. Artifact, prompt, and flags change — re-confirm the command before every run. |

## Red Flags

- Spawning a reviewer for a one-line rename or formatting change
- Treating reviewer output as authoritative without re-reading the artifact text
- Looping >3 cycles without escalating to the user
- Prompting the reviewer with "is this good?" instead of "find issues"
- Skipping doubt under time pressure on a high-stakes decision (mainnet, treasury, migration)
- Re-spawning fresh-context on an unchanged artifact — same findings; you're stalling
- **Doubt theater (checkable signal):** across 2+ cycles where the reviewer surfaced substantive findings, zero were classified actionable. You're validating, not doubting. Stop and escalate.
- Doubting only after committing — that's `/code-review`, not doubt-driven development
- Hardcoding an external CLI invocation without confirming the tool exists, is configured, and accepts that exact syntax
- **Silently skipping cross-model in an interactive cycle.** Skipping is fine; silent skipping is not.
- Falling back silently when an external CLI errors or is missing
- Stripping the contract from the reviewer's input, or passing the CLAIM (biases toward agreement)

## Interaction with Other Skills

- **`code-review-and-quality` / `/code-review`** — complementary. `/code-review` is a post-hoc diff verdict; doubt-driven is in-flight per-decision. Use both.
- **`source-driven-development`** — SDD verifies *facts about frameworks* against official docs; doubt-driven verifies *your reasoning about the artifact*. SDD checks the Anchor macro exists and is current; doubt-driven checks you used it correctly under the contract.
- **`test-driven-development`** — TDD's RED step is doubt made concrete. A failing test is a disproof attempt; when TDD applies, that failing test *is* the doubt step for behavioral claims.
- **`debugging-and-error-recovery`** — when the reviewer surfaces a real failure mode, drop into debugging to localize and fix.

## Verification

After applying doubt-driven development:

- [ ] Every non-trivial decision was named explicitly as a CLAIM before standing
- [ ] At least one fresh-context review per non-trivial artifact (a failing TDD RED test satisfies this for behavioral claims)
- [ ] The reviewer received ARTIFACT + CONTRACT — NOT the CLAIM, NOT your reasoning
- [ ] The reviewer's prompt was adversarial ("find issues"), not validating ("is it good")
- [ ] Findings classified against the artifact text using the precedence: contract misread / actionable / trade-off / noise
- [ ] A stop condition was met (trivial findings, 3 cycles, or user override)
- [ ] Interactive mode: cross-model was **explicitly offered** and the response acknowledged in the output
- [ ] Non-interactive mode: cross-model skipped and the skip announced
- [ ] Any external CLI invocation was preceded by a PATH check, a working-binary test, syntax confirmation, and explicit authorization
- [ ] For shippable code, the Definition of Done gate still runs (`fullstack-standard` → `references/definition-of-done.md`) — doubt-driven is in-flight assurance, not a substitute for the gate

## See Also

- `fullstack-standard` — the engineering bar and the Definition of Done gate this posture feeds into.
- `test-driven-development`, `source-driven-development`, `code-review-and-quality`, `debugging-and-error-recovery` — see Interaction with Other Skills above.
