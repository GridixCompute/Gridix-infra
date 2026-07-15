---
name: interview-me
description: Extracts what the user actually wants instead of what they think they should want, through a one-question-at-a-time interview until ~95% confidence about the underlying intent. Use when an ask is underspecified ("build me X" without "for whom" or "why now"), when the user explicitly invokes ("interview me", "grill me", "are we sure?", "stress-test my thinking"), or when you catch yourself silently filling in ambiguous requirements before any spec, plan, or code exists.
---

# Interview Me

## Overview

What people ask for and what they actually want are different things. They ask for "a dashboard" because that's what one asks for, not because a dashboard solves their problem. They say "make the RPC faster" without a number to hit. They say "add a token" when they mean "let people pay for compute."

The cheapest moment to find this gap is before any spec, plan, or code exists — before a single Anchor account or Astro page is committed. Once you've started building, switching costs are real, and the user rationalizes the wrong thing into a "good enough" thing. The misfit gets locked in, and in an on-chain program a locked-in misfit can mean a migration or a redeploy.

This skill closes the gap before it costs anything. The other Define-phase skills assume you already know roughly what you want: `idea-refine` generates variations from an idea, `spec-driven-development` writes the requirements down. Interview-me is the part before those — you ask one question at a time, with your best guess attached, until you can predict what the user will say before they say it.

**If you can't write the user's desired outcome in one sentence, you don't understand the ask yet — and you have no business writing code against it.**

## When to Use

Apply this skill when:

- The ask is missing at least one of: **who** the user is, **why** they want it, what **success** looks like, what the binding **constraint** is
- The request is conventional rather than specific ("build me X", "make it faster") and you can't unpack the convention without guessing
- You're tempted to start with assumptions you haven't surfaced (a chain, a framework, a data model)
- The user hasn't said which value they're optimizing when two reasonable ones are in tension (simplicity vs. flexibility, cost vs. latency, on-chain trustlessness vs. throughput)
- The user explicitly invokes: "interview me", "grill me", "before we start, are we sure?", "stress-test my thinking"

**When NOT to use:**

- The ask is unambiguous and self-contained ("rename this variable", "bump the Anchor version", "fix this typo")
- The user has explicitly asked for speed over verification
- Pure information requests ("how does a PDA work?", "what does this handler do?")
- Mechanical operations (renames, `cargo fmt`, file moves)
- You already have ≥95% confidence; re-read the stop condition below before assuming you don't

## Loading Constraints

This skill needs a live, responsive user. **Do not invoke in non-interactive contexts** like CI, scheduled runs, `/loop`, or an autonomous build loop. If you're in one of those and the ask is underspecified, flag it as a blocker for the user instead of guessing.

## The Interview Loop

### Step 1: Hypothesize, with a confidence number

Before asking anything, write down your current best read of what the user wants in **one sentence**, plus an honest confidence number (0–100%):

```
HYPOTHESIS: You want a way to answer "how is the compute network doing?" at a glance, and "dashboard" was the convention that came to mind.
CONFIDENCE: ~30% — missing: who it's for, what "metrics" means on-chain vs. off-chain, and what success looks like
```

The number forces honesty. If you wrote a high number but can't predict the user's reactions to the next three questions you'd ask, the number is wrong. Start at the confidence you can defend.

When confidence is below ~70%, append a brief reason on the same line — what's still unresolved. This tells the user exactly what the interview needs to surface, and stops the number from being a vague signal.

### Step 2: Ask one question at a time, each with a guess attached

Format:

```
Q:     <one focused question>
GUESS: <your hypothesis for the answer, with the reasoning that produced it>
```

Wait for the user to react before asking the next question.

**Why one at a time, not a batch:**

- The user can't react to your hypotheses if you bury them in a list
- Batches encourage skim-reading and surface answers
- The third question often depends on the answer to the first; asking them all at once locks in the wrong framing
- The user's energy for thinking carefully is finite — spend it one question at a time

**Why attach a guess:**

- The user reacts faster to a wrong guess than they generate an answer from scratch
- It commits you to a hypothesis you can be visibly wrong about, which keeps you honest
- It surfaces *your* assumptions — which chain, which framework, which data flow — which is exactly what the interview exists to expose

The risk is a polite user agreeing with your guess to be agreeable. Mitigate by being visibly willing to be wrong, and occasionally guess in a direction you expect the user to push back on.

### Step 3: Listen for "want vs. should want"

The most dangerous answers are the ones where the user says what a thoughtful answer *sounds like* rather than what they actually want. Watch for:

- Best-practice talk without specifics ("I want it scalable", "clean architecture", "put it on-chain")
- Deferring to convention ("the way most dApps do it", "the standard SPL approach")
- "I should probably…", "I think I'm supposed to…", "good practice says…"
- Buzzwords as goals — "decentralized", "modern", "robust", "trustless" as the answer instead of a specific outcome

When you hear these, ask:

> *"If you didn't have to justify this to anyone, what would you actually want?"*

That single question often does more work than the previous five. "Put it on-chain" frequently collapses into "I want it verifiable" — which an off-chain signature may satisfy at a fraction of the cost.

### Step 4: Restate intent in the user's own words

When confidence is high, write back what you now think the user wants. Keep it tight (5–8 lines), use their language, and structure it so they can confirm or correct line by line:

```
Here's what I now think you want:

- Outcome:      <one line>
- User:         <one line — who benefits>
- Why now:      <one line — what changed>
- Success:      <one line — how we know it worked, ideally a number>
- Constraint:   <one line — the binding limit: cost, latency, chain, deadline>
- Out of scope: <one line — what we're explicitly not doing>

Yes / no / refine?
```

Including "Out of scope" is non-negotiable. Half of misalignment is silent disagreement about what is *not* being built.

### Step 5: Confirm — explicit yes, not "whatever you think"

The gate is an explicit "yes." These are **not** yes:

- "Whatever you think is best." → Delegation, not decision — the user doesn't have 95% confidence either. Re-ask with two concrete options framed as a choice.
- "Sounds good." → Ambiguous. Ask: "Anything you'd refine?" Silence isn't confirmation.
- "Sure, let's go." → Often a polite exit, not an endorsement. Same follow-up.
- Silence, then "okay let's start." → The user gave up on the interview, didn't converge. Stop and ask what you've missed.

If they correct you, fold it in and restate. Loop until you get an explicit yes.

### The 95% Confidence Stop

You're done when you can answer yes to this:

> *Can I predict the user's reaction to the next three questions I would ask?*

If yes, you have shared understanding. Stop interviewing and produce the restate. If no, ask the next question.

This is a checkable test, not a vibe. It also has a floor: if you've gone several rounds and still can't predict, that's information about the ask, not a reason to keep grinding. Stop and say: "I've asked X questions and still can't predict your reactions. Something foundational is missing. Want to step back?"

## Output

The deliverable is a **confirmed statement of intent**: the restate from Step 4 with an explicit yes from Step 5. Specs, plans, and task lists are downstream — they consume the intent this skill produces.

If the user wants the intent to persist (a multi-session project, a handoff), offer to save it to `docs/intent/[topic].md`. Only save if they confirm — the saved doc itself implies a yes the user may not have given.

## Example

**Without `interview-me`:**

```
User:  build me a dashboard for our network metrics
Agent: <starts proposing an Astro layout and a Recharts panel>
```

The agent assumed: who it's for, what "metrics" means, whether the data is on-chain, what success looks like. Every assumption is a place the user can later say "that's not what I meant."

**With `interview-me`:**

```
User: build me a dashboard for our network metrics

Agent:
HYPOTHESIS: You want to answer "how is the network doing?" at a glance, and "dashboard" is the conventional answer that came to mind.
CONFIDENCE: ~30% — missing: who it's for, what "metrics" are, whether they live on-chain, and what success looks like

Q:     Who's asking "how are we doing?" — you alone, node operators, or prospective customers evaluating the network?
GUESS: prospective customers, since a public metrics page usually exists to build trust. If it's just for you, the whole thing can be a CLI instead of an Astro site.

User: It's for me, actually. I keep losing track of which nodes are healthy and which jobs are stuck on-chain.

Agent:
Updated read: not a public dashboard at all. It's a personal operations view over on-chain job state + node health. Confidence: ~60% — still missing: what "stuck" means and what done looks like.

Q:     Is the gap that you can't see node health, or that you can't see which on-chain jobs are stalled?
GUESS: the second — node health you can probably get from your infra, but reconciling job PDAs by hand is the tiring part.

User: Right, the jobs. I'm querying accounts manually in a terminal every time.

Agent: <continues>
```

Two questions in, "a dashboard" turned into "a read-only view over stalled job PDAs" — plausibly a small Rust or TS CLI, not an Astro site. Different artifact, different scope, different work.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The ask is clear enough" | If you can't write the user's desired outcome in one sentence right now, it isn't clear. Run Step 1 before deciding. |
| "Asking too many questions wastes their time" | 4–6 targeted questions cost minutes. Building the wrong on-chain program costs a redeploy or a migration, and the user bears it. |
| "I'll figure it out as I build" | Switching costs after code exists are 10x what they are now. Discovery during implementation is rework. |
| "They said 'whatever you think,' so I'll decide" | Delegation, not decision. Re-ask with two concrete options as a choice. |
| "I should give them several options to pick from" | Options work when the user knows what they want and is trading off. They don't know yet. Listing options widens the search; asking narrows it. |
| "If I attach my guess, I'm leading them" | Leading is the point — reacting is faster than generating. The risk is sycophancy, not leading; mitigate by being visibly willing to be wrong. |
| "We've talked enough, I get it" | Test it: can you predict their reaction to the next three questions? If not, you don't get it yet. |
| "The user said yes, we're done" | If the yes followed a vague restate or an open-ended "sounds good," it's hollow. Restate concretely and re-confirm. |
| "Just put it on-chain, that's what they meant" | "On-chain" is a mechanism, not a goal. Probe for the outcome — verifiability, custody, trustlessness — before committing to the most expensive option. |

## Red Flags

- Three or more questions in a single message — that's batching, not interviewing
- A question without your hypothesis attached — that's surveying, not committing
- Accepting "whatever you think is best" as a terminal answer
- Producing a spec, plan, or task list before the user explicitly confirmed your restate
- Questions framed as "what would be best practice?" instead of "what do you actually want?"
- A sophistication-signaling answer ("scalable", "trustless", "modern") accepted without probing
- Three or more rounds without confidence visibly rising — you're asking the wrong questions; step back and reframe
- A confidence number below ~70% with no reason attached
- Saving the intent doc before the user confirmed
- Skipping the "Out of scope" line in the restate

## Verification

After applying interview-me:

- [ ] An explicit hypothesis with a confidence number was stated in the first turn
- [ ] Every confidence number below ~70% carried a one-line reason (what's still unresolved)
- [ ] Questions were asked one at a time, each with the agent's guess attached
- [ ] At least one "what would you actually want if you didn't have to justify it?" probe ran on a sophistication- or convention-signaling answer
- [ ] A concrete restate (Outcome / User / Why now / Success / Constraint / Out of scope) was written back
- [ ] The user confirmed with an explicit yes (not "whatever you think," not "sounds good," not silence)
- [ ] At the stop point, the agent could predict reactions to the next three questions it would ask
- [ ] Any handoff to a downstream skill was framed in terms of the confirmed intent, not the original underspecified ask

## See Also

- **`idea-refine`** — downstream. If the confirmed intent is "I want X but can't scope it," hand off to generate variations against the now-explicit intent.
- **`spec-driven-development`** — downstream. If the confirmed intent is concrete ("X for Y users with Z success criteria"), hand off to write it down before any code.
- **`fullstack-standard`** — the engineering bar the eventual build must clear; interview-me only ensures you're building the *right* thing, not that you build it well.
