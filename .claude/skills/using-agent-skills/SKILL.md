---
name: using-agent-skills
description: Meta-skill that routes a task to the right eonedge workflow skill and governs how all others are discovered and invoked. Use at the start of a session, when unsure which skill applies, or when a task spans several phases (define → plan → build → verify → review → ship). Use to map an intent — new feature, bug, review, deploy — onto the skill sequence for the Rust/Anchor/Solana + TypeScript + Astro/Next + Python stack, always on top of the fullstack-standard core.
---

# Using Agent Skills

## Overview

This workspace's skills encode the processes a senior engineer follows on the
eonedge stack — Rust/Anchor/Solana, TypeScript, Astro/Next, Python. Each skill
is a workflow, not a suggestion. This meta-skill is the router: it takes the task in
front of you, identifies the phase, and points you at the right skill (or sequence
of them). One thing is always true underneath every skill — **`fullstack-standard`
is the always-on core standard.** It is not a phase you enter and leave; it is the
bar every other skill is measured against. Route first, then work — don't freehand a
task a skill already covers.

## When to Use

- At the start of a session, before touching code.
- When you're unsure which skill applies to the task.
- When a task obviously spans phases (a feature: spec → build → test → review → ship).
- When you're tempted to skip straight to code — stop and route first.

**When NOT to use:** trivial, single-step, reversible edits (a typo, a comment, a
one-line config) where routing costs more than the change. Everything non-trivial
routes.

## The Always-On Core

`fullstack-standard` sits under every route. Before writing, refactoring, reviewing,
or shipping anything, its Core Philosophy applies (minimal abstraction, type-driven
design, ship-fast-but-never-below-the-bar, the repo is the source of truth), and
nothing is "done" until its **Definition of Done** gate is green
(`fullstack-standard` → `references/definition-of-done.md`). Backend work also obeys
`references/backend-standards.md`; frontend work `references/frontend-standards.md`.
The phase skills below tell you *how* to work a stage; `fullstack-standard` tells you
what "good" means at every stage.

## Skill Discovery — route intent to a skill

```
Task arrives  ──►  fullstack-standard is already in force (always-on)
    │
    ├─ Don't know what's wanted yet? ─────────► interview-me
    ├─ Vague idea, need to shape it? ─────────► idea-refine
    │
    ├─ NEW FEATURE / non-trivial change? ─────► spec-driven-development
    │       then ─► planning-and-task-breakdown  (spec → verifiable tasks)
    │       then ─► incremental-implementation   (thin vertical slices)
    │              WITH ─► test-driven-development (failing test first, each slice)
    │       ├─ Web/UI surface? ───────────────► frontend-ui-engineering
    │       ├─ API / instruction / type contract? ─► api-and-interface-design
    │       ├─ Need official-doc-verified code? ──► source-driven-development
    │       ├─ Need the right context loaded? ────► context-engineering
    │       └─ High stakes / unfamiliar on-chain code? ─► doubt-driven-development
    │
    ├─ SOMETHING BROKE? ──────────────────────► debugging-and-error-recovery
    │       └─ then lock the fix with ───────► test-driven-development
    │
    ├─ REVIEWING code (yours or a PR)? ───────► code-review-and-quality
    │       ├─ Over-complex? ─────────────────► code-simplification
    │       ├─ Security surface? ─────────────► security-and-hardening
    │       ├─ Dependency / lockfile / CVE? ──► dependency-and-supply-chain
    │       └─ Slow / hot path? ──────────────► performance-optimization
    │
    ├─ Committing / branching? ───────────────► git-workflow-and-versioning
    ├─ CI/CD pipeline work? ──────────────────► ci-cd-and-automation
    ├─ Retiring / migrating old code or accounts? ─► deprecation-and-migration
    ├─ Changing a deployed DB schema / backfill? ─► database-schema-migrations
    ├─ Recording a decision / ADR / docs? ────► documentation-and-adrs
    ├─ Adding logs / metrics / alerts? ───────► observability-and-instrumentation
    │
    └─ SHIPPING / deploying (devnet→mainnet, release)? ─► shipping-and-launch
            └─ gated by the Definition of Done (fullstack-standard)
```

Common intents, at a glance:

- **"Build me X."** → `spec-driven-development` → `planning-and-task-breakdown` →
  `incremental-implementation` **with** `test-driven-development`. Don't start at code.
- **"X is broken / erroring."** → `debugging-and-error-recovery`, then a regression
  test via `test-driven-development`.
- **"Review this."** → `code-review-and-quality` (branch into simplification /
  security / performance as the diff warrants).
- **"Ship it / deploy to mainnet."** → `shipping-and-launch`, which will not let you
  past the Definition of Done gate.

## Core Operating Behaviors

Non-negotiable, active under every skill:

### 1. Surface assumptions
Before anything non-trivial, state them and invite correction:

```
ASSUMPTIONS I'M MAKING:
1. <about requirements>
2. <about the account / type model>
3. <about scope>
→ Correct me now or I proceed with these.
```

Don't silently fill ambiguous requirements. Wrong-assumption-and-run is the most
common failure. Surfacing uncertainty early is cheaper than rework.

### 2. Manage confusion actively
On an inconsistency, conflict, or unclear spec: **STOP.** Don't guess. Name the
confusion, present the trade-off or ask the question, wait for resolution.
*Good:* "The spec says the treasury is a keypair but ADR-004 says it's a PDA — which
wins?" *Bad:* silently picking one and hoping.

### 3. Push back when warranted
You are not a yes-machine. When an approach has a real problem, name it, quantify the
downside ("this adds a second signer round-trip", not "might be slower"), propose an
alternative, then accept an informed override. Sycophancy is a failure mode; honest
technical disagreement beats false agreement.

### 4. Enforce simplicity
Your instinct over-builds; resist it (this *is* `fullstack-standard`'s minimal
abstraction). Before finishing, ask: fewer lines? Do these layers earn their keep?
Would a staff engineer say "why didn't you just…"? If 100 lines would do and you
wrote 1000, you failed. Prefer the boring, direct path.

### 5. Maintain scope discipline
Touch only what the task requires. Do NOT: strip comments you don't understand,
"clean up" orthogonal code, refactor adjacent systems as a side effect, delete
seemingly-unused code without approval, or add unrequested features. Surgical
precision, not unsolicited renovation.

### 6. Verify, don't assume
Every skill has a verification step; a task isn't done until it passes with
*evidence* — passing tests, build output, a real devnet transaction — never "seems
right." The per-skill check is local; the project-wide bar over *every* change,
whichever skill is active, is the **Definition of Done**
(`fullstack-standard` → `references/definition-of-done.md`).

## Skill Rules

1. **Route before you start.** Check for an applicable skill; skills prevent the
   common mistakes.
2. **Skills are workflows, not suggestions.** Follow the steps in order; don't skip
   verification.
3. **Multiple skills compose.** A feature may run `idea-refine` →
   `spec-driven-development` → `planning-and-task-breakdown` →
   `incremental-implementation` + `test-driven-development` → `code-review-and-quality`
   → `code-simplification` → `documentation-and-adrs` → `shipping-and-launch`.
4. **When in doubt, start with a spec.** Non-trivial and no spec →
   `spec-driven-development`.
5. **`fullstack-standard` is always on.** It is never skipped and never "finished".

## The 26 skills, grouped by phase

`fullstack-standard` is the always-on core beneath all six phases.

**Define**
| Skill | One line |
|---|---|
| interview-me | Surface what the user actually wants before any spec or code exists. |
| idea-refine | Shape a vague idea through divergent then convergent thinking. |
| spec-driven-development | Requirements and acceptance criteria before code. |

**Plan**
| Skill | One line |
|---|---|
| planning-and-task-breakdown | Decompose a spec into small, verifiable tasks. |

**Build**
| Skill | One line |
|---|---|
| incremental-implementation | Thin vertical slices; verify each before expanding. |
| source-driven-development | Verify against official docs/IDL before implementing. |
| doubt-driven-development | Adversarial fresh-context review of every non-trivial (esp. on-chain) decision. |
| context-engineering | Load the right context at the right time. |
| frontend-ui-engineering | Production-quality, accessible Astro/Next UI. |
| api-and-interface-design | Stable interfaces and type/IDL contracts. |

**Verify**
| Skill | One line |
|---|---|
| test-driven-development | Failing test first (incl. Anchor failure cases), then make it pass. |
| browser-testing-with-devtools | Drive the real browser to verify UI at runtime. |
| debugging-and-error-recovery | Reproduce → localize → fix → guard with a test. |

**Review**
| Skill | One line |
|---|---|
| code-review-and-quality | Multi-axis review against the Definition of Done. |
| code-simplification | Cut unnecessary complexity while preserving behavior. |
| security-and-hardening | Hostile-input assumptions, account-constraint checks, least privilege, secret hygiene. |
| dependency-and-supply-chain | Third-party deps as attack surface — audit, pin, license-check, lockfile hygiene. |
| performance-optimization | Measure first; optimize only what the data says matters. |

**Ship**
| Skill | One line |
|---|---|
| git-workflow-and-versioning | Atomic conventional commits, clean history. |
| ci-cd-and-automation | Automated quality gates on every change. |
| deprecation-and-migration | Retire old systems / account layouts and migrate safely. |
| database-schema-migrations | Zero-downtime off-chain schema changes: forward+rollback, expand-contract, batched backfills. |
| documentation-and-adrs | Record the *why*; ADRs for irreversible on-chain decisions. |
| observability-and-instrumentation | Structured logs (tracing/loguru), RED metrics, symptom alerts. |
| shipping-and-launch | Pre-launch gate, localnet→devnet→mainnet rollout, monitoring, rollback. |

**Meta (always-on router):** `using-agent-skills` (this skill), sitting over
`fullstack-standard`.

## Lifecycle Sequence (full feature)

```
1  interview-me / idea-refine   → extract & shape intent
2  spec-driven-development       → define what we're building
3  planning-and-task-breakdown   → verifiable chunks
4  context-engineering           → load the right context
5  source-driven-development      → verify against official docs / IDL
6  incremental-implementation    → build slice by slice
   + test-driven-development     → prove each slice (happy path AND failure cases)
   + observability-and-instrumentation → instrument as you build (parallel, not after)
   + doubt-driven-development    → cross-examine non-trivial on-chain decisions in-flight
7  code-review-and-quality       → review before merge
   + code-simplification / security-and-hardening / performance-optimization as warranted
   + dependency-and-supply-chain → audit/pin deps touched; fail on high-severity advisories
8  git-workflow-and-versioning   → clean commit history
9  documentation-and-adrs        → record the decisions
10 deprecation-and-migration     → retire old code/accounts when needed
   + database-schema-migrations  → evolve off-chain DB schema safely (zero-downtime)
11 shipping-and-launch           → deploy safely (DoD gate → devnet → mainnet)
```

A bug fix is shorter: `debugging-and-error-recovery` → `test-driven-development`
(regression test) → `code-review-and-quality`.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "This is simple, I'll skip straight to code." | Skills exist because "simple" tasks are where wrong assumptions hide. Route first. |
| "I don't need a spec, it's obvious." | If it's obvious, the spec takes two minutes and proves you agree with yourself. If it isn't, you just avoided rework. |
| "fullstack-standard is just background." | It's the bar every skill is measured against and the gate on "done". Ignoring it means nothing is actually finished. |
| "I'll pick one interpretation and keep moving." | Guessing past a conflict is the top failure mode. Stop, name it, resolve it. |
| "Verification is a formality." | "Seems right" has no evidence. A green DoD gate and a real devnet tx do. |
| "One skill is enough for this." | Real work composes skills. A feature is a sequence, not a single step. |

## Red Flags

- Writing code before routing the task to a skill.
- Building a non-trivial feature with no spec.
- Any skill's steps followed out of order, or its verification skipped.
- Treating the Definition of Done as optional or "later".
- Plowing past a noticed inconsistency instead of stopping.
- Sycophantic agreement to an approach with a clear problem.
- Scope creep — refactoring adjacent code the task never asked for.

## Verification

- [ ] The current task is mapped to a skill (or an ordered sequence of them).
- [ ] `fullstack-standard` is in force; you know which references apply
      (backend / frontend).
- [ ] Assumptions were surfaced and confusions resolved before implementation.
- [ ] Each active skill's own verification step passed with evidence.
- [ ] The Definition of Done gate is green before anything is called "done"
      (`fullstack-standard` → `references/definition-of-done.md`).
- [ ] Scope stayed within what was asked.

## See Also

- `fullstack-standard` — the always-on core standard beneath every route; its
  Definition of Done is the universal gate.
- Every phase skill named in the tables above — this skill's whole job is to send
  you to the right one.
