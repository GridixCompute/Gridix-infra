---
name: idea-refine
description: Refines raw ideas into sharp, buildable concepts through structured divergent and convergent thinking, ending in a one-page brief with an explicit "Not Doing" list. Use when an idea is still vague, when you need to stress-test assumptions before committing to a spec or plan, or when you want to expand options before converging on one. Triggers on "ideate", "refine this idea", "stress-test my plan".
---

# Idea Refine

## Overview

Refines raw ideas into sharp, actionable concepts worth building, through structured divergent thinking (open the idea up) then convergent thinking (cut it down). It sits between `interview-me` (which extracts what the user actually wants) and `spec-driven-development` (which writes the chosen thing down). It does not produce code — it produces a decision and a one-pager you can spec against.

The failure mode it prevents is committing to the first framing of an idea and discovering, three PDAs or three Astro routes later, that a simpler or sharper version was sitting right there. **Simplicity is the ultimate sophistication — push toward the simplest version that still solves the real problem.**

## When to Use

- An idea is still a vibe, not a concept ("something for paying node operators", "a token thing")
- You have one idea and suspect there are better adjacent ones you haven't considered
- You want to stress-test assumptions before locking scope in a spec
- The user says "ideate", "refine this idea", "stress-test my plan"

**When NOT to use:**

- The concept is already sharp and the user just wants it written down → go to `spec-driven-development`
- You don't yet know who it's for or why → run `interview-me` first
- It's a mechanical or well-defined change → skip straight to building against the standard

## Guiding Principles

- Simplicity is the ultimate sophistication. The 10x-simpler version usually wins.
- Start from the user experience, work backwards to the technology — not "we have a Solana program, what can it do?"
- Say no to 1,000 things. Focus beats breadth.
- Challenge every assumption. "How dApps usually do it" is not a reason.
- Be honest, not supportive. A good ideation partner is not a yes-machine.
- Minimal abstraction applies to ideas too: the fewer moving parts, contracts, and services the concept needs, the better (see `fullstack-standard`).

## The Three Phases

```
UNDERSTAND & EXPAND  ──→  EVALUATE & CONVERGE  ──→  SHARPEN & SHIP
   (divergent)              (convergent)             (one-pager)
        │                        │                        │
        ▼                        ▼                        ▼
   5–8 variations          2–3 directions,          brief + Not Doing,
   from real context       stress-tested            user confirms
```

Adapt to the conversation — this is a dialogue, not a script.

### Phase 1: Understand & Expand (Divergent)

**Goal:** take the raw idea and open it up.

1. **Restate the idea** as a crisp "How Might We" problem statement. This forces clarity on what's actually being solved.

2. **Ask 3–5 sharpening questions** — no more:
   - Who is this for, specifically?
   - What does success look like (ideally a number)?
   - What are the real constraints — time, cost, chain, latency, team-of-one?
   - What's been tried before?
   - Why now?

   Do NOT proceed until you know who it's for and what success looks like. If those are missing, stop and run `interview-me`.

3. **Generate 5–8 idea variations** using these lenses — pick the ones that fit, don't run all mechanically:
   - **Inversion:** "What if we did the opposite?"
   - **Constraint removal:** "What if cost / time / chain-choice weren't a factor?"
   - **Audience shift:** "What if this were for node operators instead of end users?"
   - **Combination:** "What if we merged this with an adjacent idea?"
   - **Simplification:** "What's the version that's 10x simpler — off-chain signature instead of a program? A static Astro page instead of an app?"
   - **10x version:** "What would this look like at massive scale?"
   - **Expert lens:** "What would a Solana protocol engineer find obvious that an outsider wouldn't?"

   Push beyond what the user first asked for. Each variation should have a reason it exists, not just be a bullet.

**If running inside a repo:** use `Glob`, `Grep`, `Read` to scan for real context — existing Anchor programs, shared types crates, Astro/Next routes, prior art. Ground variations in what actually exists; the repo is the source of truth. Reference specific files when relevant. An idea that fights the existing architecture has a cost — name it.

### Phase 2: Evaluate & Converge

After the user reacts (says what resonates, pushes back, adds context), switch to convergent mode.

1. **Cluster** the surviving ideas into 2–3 distinct directions. Each should feel meaningfully different, not variations on a theme.

2. **Stress-test** each direction against three criteria:
   - **User value:** Who benefits, how much? Painkiller or vitamin?
   - **Feasibility:** Technical and resource cost for a solo builder. What's the hardest part — a novel PDA design, a signer/CPI edge case, an SPL integration, a real-time data pipeline? Does it fit the stack, or drag in a new one?
   - **Differentiation:** What makes it genuinely different? Would someone switch from their current solution?

3. **Surface hidden assumptions.** For each direction, name explicitly:
   - What you're betting is true but haven't validated
   - What could kill this idea (a chain limitation, a cost floor, a missing user)
   - What you're choosing to ignore, and why that's okay for now

   This is where most ideation fails. Don't skip it.

**Be honest, not supportive.** If an idea is weak, say so with kindness and specificity. Push back on complexity, question real value, point out when the emperor has no clothes.

### Phase 3: Sharpen & Ship

Produce a concrete one-pager that moves work forward:

```markdown
# [Idea Name]

## Problem Statement
[One-sentence "How Might We" framing]

## Recommended Direction
[The chosen direction and why — 2–3 paragraphs max]

## Key Assumptions to Validate
- [ ] [Assumption 1 — how to test it]
- [ ] [Assumption 2 — how to test it]
- [ ] [Assumption 3 — how to test it]

## MVP Scope
[The minimum version that tests the core assumption. In / out.
 Name the stack it lands on: e.g. one Anchor instruction + a typed
 TS SDK method, or a static Astro page — nothing more.]

## Not Doing (and Why)
- [Thing 1] — [reason]
- [Thing 2] — [reason]
- [Thing 3] — [reason]

## Open Questions
- [What must be answered before building]
```

**The "Not Doing" list is the most valuable part.** Focus is about saying no to good ideas. Make the trade-offs explicit.

Ask if the user wants this saved to `docs/ideas/[idea-name].md` (or a location of their choosing). Only save if they confirm.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "More variations means a better search" | 20 shallow ideas beat nothing but hide the good one. 5–8 well-reasoned variations is the target; quantity is noise. |
| "The idea's good, I don't need to stress-test it" | Untested assumptions are the #1 killer of good ideas. Name what could kill it before you commit a spec to it. |
| "I'll figure out who it's for while building" | Every good idea starts with a person and their problem. No user, no phase 2 — run `interview-me`. |
| "Let's just put it on-chain, it's cooler" | On-chain is a cost, not a feature. If an off-chain signature or a static page solves it, that's the sharper idea. |
| "Skip to the one-pager, I know what I want" | If you knew, you wouldn't be ideating. Phase 1 and 2 exist to make sure the one-pager describes the right thing. |
| "Pushing back will seem unhelpful" | Yes-machining a weak idea is the least helpful thing you can do. Honest and specific beats supportive and vague. |
| "The existing repo is irrelevant to the idea" | The existing architecture is both a constraint and an opportunity. Ignoring it produces ideas that cost a rewrite. |

## Red Flags

- Generating 20+ shallow variations instead of 5–8 considered ones
- Skipping the "who is this for" question
- No assumptions surfaced before committing to a direction
- Yes-machining a weak idea instead of pushing back with specificity
- Producing a direction with no "Not Doing" list
- Ignoring existing repo constraints (chain, stack, types) when ideating inside a project
- Jumping straight to the Phase 3 one-pager without running Phases 1 and 2
- The MVP scope quietly drags in a second chain, a new framework, or a service the concept doesn't need

## Verification

After an ideation session:

- [ ] A clear "How Might We" problem statement exists
- [ ] The target user and success criteria are defined (success is a number where possible)
- [ ] Multiple directions were explored, not just the first idea
- [ ] Hidden assumptions are listed with validation strategies
- [ ] A "Not Doing" list makes the trade-offs explicit
- [ ] MVP scope names the concrete stack it lands on and stays minimal
- [ ] The output is a concrete one-pager, not just conversation
- [ ] The user confirmed the direction before any implementation work began

## See Also

- **`interview-me`** — upstream. Run it first when you don't yet know who the idea is for or why now.
- **`spec-driven-development`** — downstream. Feed the confirmed one-pager into a spec before writing code.
- **`fullstack-standard`** — the engineering bar the chosen idea will be built against; keep "minimal abstraction" in mind while ideating so the MVP is cheap to ship.
