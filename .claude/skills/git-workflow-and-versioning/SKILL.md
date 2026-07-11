---
name: git-workflow-and-versioning
description: Structures git workflow, branching, commits, and release versioning for eonedge's polyglot stack (Rust/Anchor, TypeScript, Astro/Next, Python). Use when making any code change. Use when committing, branching, resolving conflicts, or organizing parallel work streams. Use when cutting a release, choosing a semver bump, tagging an on-chain program or SDK, or writing a changelog. Use when working directly on a deployed/ephemeral compute node before it restarts or redeploys.
---

# Git Workflow and Versioning

## Overview

Git is your safety net. Commits are save points, branches are sandboxes, history
is documentation — and on this stack, the repo is the only source of truth. Code
that lives only in your head, only in a chat, or only on a deployed node does not
exist. Disciplined version control is what keeps agent-speed changes reviewable,
reversible, and real. **If it isn't committed, it didn't happen.**

## When to Use

- Any code change — every change flows through git.
- Committing, branching, resolving conflicts, splitting work.
- Cutting a release of an on-chain program, an SDK, or a service.
- Choosing a semver bump, tagging, or writing a changelog.
- **Before stopping or redeploying a compute node you worked on directly.**

**When NOT to use:** never — but for the pre-ship quality gate itself defer to
`fullstack-standard` → `references/definition-of-done.md`; this skill governs the
*history and versioning*, not the lint/test bar.

## Branching & Commit Discipline (house rules)

These override any generic advice. They match `fullstack-standard`.

- **Never commit to the default branch directly.** Branch first, always.
- **Commit and push only when the user asks.** Do the work; stage nothing on your
  own initiative unless told to.
- **Squash and merge.** Feature branches collapse to one clean commit on the
  default branch — so the *branch* can hold messy WIP, but the merged commit must
  be atomic and well-described.
- **Short-lived branches.** Merge within 1–3 days. A long-lived branch diverges,
  rots, and turns integration into a conflict-resolution project. Prefer a feature
  flag over a branch that lives for weeks (see `ci-cd-and-automation`).
- **Delete branches after merge.**

### Branch names — prefix by change type

```
feat/<short-desc>       feat/pda-treasury-init
fix/<short-desc>        fix/rent-exempt-balance
docs/<short-desc>       docs/sdk-quickstart
chore/<short-desc>      chore/bump-anchor-0.31
refactor/<short-desc>   refactor/split-types-crate
test/<short-desc>       test/failure-case-bad-signer
```

The seven prefixes are the same seven Conventional Commit types below. One change
type per branch.

### Conventional Commits — `type(scope): description`

```
feat(program): add PDA-derived treasury with rent-exempt init

Treasury authority is now a program-derived address seeded on the
market pubkey, so no client-supplied authority can drain it. Every
withdraw CPI re-checks has_one + bump. Failure cases covered in
tests/treasury_withdraw.rs.
```

- Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`.
- Scope is optional but useful: `program`, `sdk`, `web`, `indexer`, crate name.
- Subject line imperative, lower-case, no trailing period, ~50 chars.
- Body explains **why**, not what — the diff already says what. Note invariants,
  the hostile input you defended against, the failure cases you covered.

```
# Good — explains intent
fix(sdk): reject unconfirmed tx before returning signature

# Bad — restates the diff
update client.ts
```

## Core Principles

### 1. Commit early, commit often

```
Implement slice → gate it → verify → commit → next slice
NOT: implement everything → hope → one giant commit
```

Each successful increment is a save point. If the next change breaks something,
`git reset --hard HEAD` returns you to the last known-good state — you lose one
increment, never a day.

### 2. Atomic commits — one logical thing each

```
# Good
a1b2c3d feat(program): add place_order instruction with account checks
d4e5f6g test(program): cover bad-signer and wrong-PDA failure paths
h7i8j9k feat(sdk): typed placeOrder wrapper exporting OrderArgs
m1n2o3p feat(web): order form consuming the SDK's exported types

# Bad — everything mashed together
x1y2z3a add orders, fix indexer, bump deps, refactor errors
```

### 3. Keep concerns separate

Formatting ≠ behavior. Refactor ≠ feature. A `cargo fmt` / `prettier` sweep and a
logic change are two commits, ideally two PRs — each easier to review and revert.
A refactor that "also fixes a bug" hides the fix; split them.

### 4. Size your changes

Target ~100 lines per commit/PR; ~300 is fine for one logical change; >~1000 must
be split (see `code-review-and-quality` for splitting strategies). On-chain
changes especially: a small, self-contained instruction diff is far easier to
audit than a sprawling one.

## The Save-Point Pattern

```
Agent starts work
    │
    ├── change → gate passes? → commit → continue
    │            gate fails?  → git reset --hard HEAD → investigate
    ├── change → gate passes? → commit → continue
    │            gate fails?  → git reset --hard HEAD → investigate
    └── feature complete → branch is a clean, atomic history → squash-merge
```

You never lose more than one increment. If an agent goes off the rails, reset to
the last green commit.

## Pre-Commit Hygiene (when the user asks you to commit)

Review what you're about to commit and run the gate for the layer(s) you touched:

```bash
git diff --staged                      # eyeball the whole change
git diff --staged | grep -iE "secret|api[_-]?key|private_key|seed phrase|BEGIN .*PRIVATE"
```

Then the real gate — do not shortcut it (`fullstack-standard` →
`references/definition-of-done.md`):

```bash
# Backend (Rust)          # Backend (Python)     # Frontend / TS
cargo clippy -- -D warnings   ruff check .        pnpm lint
cargo fmt --check             ruff format --check .   pnpm prettier -c .
cargo test                    pytest              pnpm tsc --noEmit && pnpm test
anchor test                                       # on-chain, local validator
```

Never commit a keypair, `.env`, `target/`, `.anchor/`, `node_modules/`, `dist/`,
`.next/`, or an on-chain build artifact. A `.gitignore` covering those exists
before the first commit. If you spot a committed credential, stop and flag it for
rotation — do not just delete it in a later commit (git remembers).

## Deploy / Node Discipline (critical — ephemeral storage)

Most GPU/compute nodes run on **ephemeral container storage**: code that exists
only on the node is destroyed on restart or redeploy. This is the most common way
work is silently lost on this stack. After ANY work directly on a deployed node,
**before** you stop, restart, or redeploy it:

```
1. git status && git diff        # on the node checkout — what's uncommitted?
2. Commit to a branch and push,  # OR copy the files back to the local repo
   then push.                    #    and commit there.
3. git status                    # confirm the tree is CLEAN before teardown.
```

If `git status` is not clean and you can't push, do not redeploy — you will lose
the work. Treat "the node has my only copy" as an incident.

## Using Git for Debugging

```bash
git bisect start && git bisect bad HEAD && git bisect good <known-good>  # find the breaking commit
git log --oneline -20
git log --grep="treasury" --oneline
git blame program/src/instructions/withdraw.rs
git diff HEAD~5..HEAD -- program/
```

## Release & Versioning

Commits are how *you* track change; a **version** is how your *consumers* track
it. The moment anything depends on your code — the on-chain program a client SDK
targets, a published `@eonedge/*` package, a deployed service another team calls —
"latest on main" stops answering "what am I running, and is it safe to upgrade?"
A version number and a changelog are that contract.

### Semantic Versioning

```
MAJOR  breaking — consumers must change their code / their tx-building to upgrade
MINOR  additive, backward-compatible — safe to upgrade
PATCH  bug fix, backward-compatible — safe to upgrade
```

The number is a promise; make the code match it. When unsure whether a change is
breaking, assume it is — a surprise major is far cheaper than a broken consumer.

**On-chain reality:** a deployed program's account layout and instruction
interface *are* the public API. Reordering `#[account(...)]` fields, changing a
PDA seed, altering an instruction's arg order, or shrinking an account is a
**MAJOR** change — old clients build transactions that now fail or, worse, resolve
to the wrong PDA. Migrating deployed program state across a major bump is its own
discipline: follow `deprecation-and-migration`.

**SDK reality:** the backend exports the types; the frontend imports them. Changing
an exported type's shape is a breaking change to every client that imports it —
version the SDK accordingly, don't just edit the type and move on.

### Tag the release; let the tag be the source of truth

A release is an immutable point in history, not a moving branch:

```bash
git tag -a v1.4.0 -m "Release 1.4.0"
git push origin v1.4.0
```

Derive the shipped version from the tag (Cargo/package metadata, program IDL
version) rather than hand-editing it in scattered files, so the artifact, the tag,
and the changelog can never disagree. For an on-chain program, record the deployed
program ID and the tag together — the tag must reproduce the exact bytecode.

### Keep a changelog written for humans

A changelog is not `git log`. It's the curated, consumer-facing answer to "what
changed and do I care?" — grouped `Added / Changed / Fixed / Deprecated / Removed
/ Security`, newest on top, phrased by user impact, not internal mechanics.

```markdown
## [1.4.0] - 2026-06-12
### Added
- Bulk order placement via a single instruction.
### Changed
- **BREAKING (program):** `place_order` now takes `market` before `side`;
  rebuild client tx. Migration: see deprecation-and-migration guide.
### Fixed
- Rent-exemption underflow when closing an empty position account.
### Security
- Withdraw now re-checks `has_one = authority` on every CPI.
```

Write the entry in the same change that makes the change, while the impact is
fresh — not reconstructed from commit archaeology at release time. Breaking
changes get a migration note and a deprecation window (`deprecation-and-migration`).
Actually shipping the release — cutting the build, deploying, monitoring — is a
separate step; this section is the versioning contract that feeds it.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll commit when the feature is done" | One giant commit is impossible to review, debug, or revert. Commit each verified slice. |
| "The message doesn't matter" | Messages are documentation. Future you and future agents read them to understand why a PDA seed changed. |
| "It's fine on the node, I'll sync later" | Ephemeral storage wipes on redeploy. "Later" is after the code is gone. Commit before teardown, every time. |
| "It's just a small fix, bump the patch" | Check what consumers observe. A changed account layout or instruction arg order is a MAJOR, whatever the diff size. |
| "The account order is an internal detail" | On-chain, the layout *is* the ABI. Reordering it breaks every deployed client — that's a breaking change. |
| "I'll split the refactor and feature later" | Mixed commits hide the behavior change inside noise. Split before submitting, not after. |
| "The changelog is just the commit log" | Commits are for you; the changelog is curated by consumer impact. Dumping commits buries what matters. |
| "I'll commit straight to main, it's my repo" | Never commit to the default branch directly. Branch, then squash-merge — even solo. |

## Red Flags

- Uncommitted work sitting on an ephemeral node about to redeploy.
- Committing directly to the default branch.
- Committing or pushing without being asked.
- Commit messages like "fix", "update", "wip", "misc".
- Formatting-only churn mixed with behavior changes in one commit.
- A committed keypair, `.env`, seed phrase, or on-chain build artifact.
- A changed account layout / instruction interface shipped under a minor or patch.
- A release with no tag, or a version hand-edited out of sync with the tag.
- A user-facing release with no changelog entry, or a changelog that's dumped commits.
- Long-lived branches diverging from the default branch; force-pushing shared branches.

## Verification

For every commit (once the user has asked you to commit):

- [ ] Commit does one logical thing; concerns aren't mixed.
- [ ] Conventional-commit message; body explains *why* and any invariant/failure case.
- [ ] The Definition-of-Done gate passed for the layers touched (real command output).
- [ ] `git diff --staged` reviewed; no secrets, keypairs, or build artifacts.
- [ ] On a branch, not the default branch; ready to squash-merge.

Before tearing down a deployed node:

- [ ] `git status` clean on the node; work committed to a branch and pushed (or copied back and committed).

For every release (anything with consumers):

- [ ] Version bump matches the change: breaking → major, additive → minor, fix → patch.
- [ ] Account layout / instruction interface / exported-type changes classified correctly (breaking = major).
- [ ] Release is tagged; shipped version is derived from the tag, not hand-edited.
- [ ] Changelog has a curated, human-readable entry grouped by impact, with migration notes for breaking changes.

## See Also

- `fullstack-standard` — the engineering bar; commit discipline and node discipline live there too. Gate: `references/definition-of-done.md`.
- `ci-cd-and-automation` — feature flags over long branches; branch protection and required status checks.
- `deprecation-and-migration` — how to ship a breaking (major) change to a deployed program or SDK safely.
- `code-review-and-quality` — splitting oversized changes.
