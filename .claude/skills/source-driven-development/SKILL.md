---
name: source-driven-development
description: Grounds every framework-specific decision in official documentation for the eonedge stack — Solana/Anchor, @solana/web3.js, Astro 5, Next 15, Tailwind v4, Rust crates, and Python libs. Use when you want authoritative, source-cited code free of outdated patterns. Use when building with any framework or library where correctness matters, or any time you're about to write framework-specific code from memory.
---

# Source-Driven Development

## Overview

Every framework-specific code decision must be backed by official documentation. Don't implement from memory — verify, cite, and let the source be checkable. Training data goes stale, APIs get deprecated, best practices evolve. This is acute on this stack: Solana runtime and Anchor macros change across versions, `@solana/web3.js` has a v1/v2 split, Next 15 and Astro 5 and Tailwind v4 each shipped breaking changes. **Confidence is not evidence — the repo and the official docs are the source of truth.**

## When to Use

- Writing framework/library-specific code: Anchor account macros, `@solana/web3.js` calls, Astro/Next routing or data fetching, Tailwind v4 config, a Rust crate's API, a Python lib's interface
- Boilerplate or starter patterns that will be copied across the project
- The user asks for documented, verified, or "correct" implementation
- Features where the recommended approach matters (accounts/PDAs, transactions, forms, routing, data fetching, auth, server vs client components)
- Reviewing or improving code that uses framework-specific patterns
- Any time you're about to write framework-specific code from memory

**When NOT to use:**
- Correctness doesn't depend on a version (renaming, typos, moving files)
- Pure logic identical across versions (loops, conditionals, a data transform)
- The user explicitly wants speed over verification ("just do it quickly")

This spans both layers. Frontend framework rules live in `fullstack-standard` → `references/frontend-standards.md`; backend/on-chain in `references/backend-standards.md`.

## The Process

```
DETECT ──→ FETCH ──→ IMPLEMENT ──→ CITE
  │          │           │            │
  ▼          ▼           ▼            ▼
 What       Get the     Follow the   Show your
 stack &    exact doc   documented   sources
 version?   page        patterns
```

### Step 1: Detect Stack and Versions

Read the dependency manifest to pin exact versions before writing anything:

```
Cargo.toml            → Rust crates, Anchor (anchor-lang / anchor-spl), Solana SDK
Anchor.toml           → anchor + solana CLI versions, cluster
package.json          → @solana/web3.js (v1 vs v2!), Astro, Next, React, Tailwind
pnpm-lock.yaml        → the resolved versions actually installed
pyproject.toml        → Python libs, ruff, tooling
```

State what you found explicitly:

```
STACK DETECTED:
- anchor-lang 0.30.1 (Cargo.toml)
- solana-program 1.18.x (Cargo.toml)
- @solana/web3.js 1.95.x (package.json)  ← v1 API, NOT the v2 @solana/* modular packages
- Next 15.1 / Tailwind 4.0 (package.json)
→ Fetching official docs for the relevant patterns against these versions.
```

The `@solana/web3.js` v1-vs-v2 distinction is the single most common way to ship wrong code here — v2 is a different, modular API (`@solana/kit` / `@solana/*`). Confirm which one is installed before writing a single import. If versions are missing or ambiguous, **ask the user** — the version determines which pattern is correct.

### Step 2: Fetch Official Documentation

Fetch the specific page for the feature, not the homepage. Extract the key patterns and note deprecations.

**Source hierarchy (order of authority):**

| Priority | Source | Examples for this stack |
|---|---|---|
| 1 | Official docs | solana.com/docs, docs.rs/anchor-lang, anchor's book (`www.anchor-lang.com`), solana-web3js docs, docs.astro.build, nextjs.org/docs, tailwindcss.com/docs |
| 2 | Official blog / changelog / release notes | Anchor & Solana release notes, nextjs.org/blog, astro.build/blog, GitHub releases for the pinned crate/package |
| 3 | Web standards & platform refs | MDN, web.dev, html.spec.whatwg.org |
| 4 | Runtime / compatibility data | caniuse.com, node.green; `docs.rs` for exact crate API by version |

**Stack-specific canonical sources:**
- **Solana / Anchor**: `solana.com/docs`, the Anchor book at `www.anchor-lang.com`, and `docs.rs/anchor-lang/<version>` for the exact macro/attribute API you're pinned to. `docs.rs` is version-addressable — always fetch the page for your installed version, not "latest."
- **@solana/web3.js**: the versioned reference matching v1 vs v2. Never mix the two APIs in one file.
- **Astro 5 / Next 15 / Tailwind v4**: `docs.astro.build`, `nextjs.org/docs` (App Router; check server vs client component guidance), `tailwindcss.com/docs` (v4 config is CSS-first — the old `tailwind.config.js` shape changed).
- **Rust crates**: `docs.rs/<crate>/<version>`. **Python libs**: the project's official docs for the pinned version.

**Not authoritative — never cite as a primary source:** Stack Overflow, blog tutorials (even popular ones), AI-generated summaries, your own training data (verifying it is the whole point).

**Be precise about what you fetch:**
```
BAD:  Fetch the Anchor homepage
GOOD: Fetch www.anchor-lang.com/docs/account-constraints  (for `has_one` / `seeds` / `bump`)

BAD:  Search "solana send transaction best practice"
GOOD: Fetch the @solana/web3.js v1 reference for sendAndConfirmTransaction
```

When official sources conflict (a migration guide contradicts the API reference), surface the discrepancy and verify which pattern actually works against the detected version — ideally by writing a test (`test-driven-development`).

### Step 3: Implement Following Documented Patterns

Write code matching what the docs show for your version:
- Use the API signatures and account-constraint attributes from the docs, not from memory
- If the docs show a newer way (e.g. Anchor's current constraint syntax, Next's current data-fetching), use it
- If the docs deprecate a pattern, don't use it
- If the docs don't cover something, flag it as unverified
- Keep it on the bar: typed errors (`thiserror`, `?`), no `unwrap()` in runtime paths, no `any`; on-chain, validate every account constraint the docs describe

**When docs conflict with existing project code**, surface it — don't silently pick:
```
CONFLICT DETECTED:
Existing code fetches accounts with `program.account.foo.fetch(...)` (older Anchor TS pattern),
but the pinned @coral-xyz/anchor docs recommend <current pattern>.
(Source: <official URL>)
Options:
A) Modern documented pattern — consistent with current docs
B) Match existing code — consistent with the codebase
→ Which do you prefer?
```

### Step 4: Cite Your Sources

Every framework-specific pattern gets a checkable citation.

**In code comments:**
```rust
// Anchor account constraint: `has_one` ties `treasury` to the authority.
// Source: https://www.anchor-lang.com/docs/account-constraints#has_one
#[account(has_one = authority)]
pub treasury: Account<'info, Treasury>,
```

**In conversation:**
```
Using PDA seeds `[b"treasury", authority.key().as_ref()]` with an explicit bump,
per the Anchor account-constraints docs. Deriving deterministically instead of
trusting a client-supplied address.
Source: https://www.anchor-lang.com/docs/pdas
```

**Citation rules:**
- Full URLs, not shortened
- Prefer deep links with anchors (they survive doc restructuring better than top-level pages)
- Pin to the version where the API is version-specific (`docs.rs/anchor-lang/0.30.1/...`)
- Quote the relevant passage when it supports a non-obvious decision
- Include runtime/browser support data when recommending a platform feature
- If you can't find docs for a pattern, say so:
```
UNVERIFIED: No official documentation found for this pattern against the pinned
version. Based on training data and may be outdated. Verify before shipping.
```
Honesty about what you couldn't verify beats false confidence.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'm confident about this API" | Confidence is not evidence. Training data has outdated patterns that look right and break against the pinned version. Verify. |
| "web3.js is web3.js" | v1 and v2 are different APIs. Guessing which is installed is the #1 source of broken Solana code here. Check `package.json` first. |
| "Fetching docs wastes tokens" | Hallucinating a macro or a signature wastes an hour of the user's debugging plus a redeploy. One fetch prevents it. |
| "The docs won't have what I need" | If the docs don't cover it, that's information — the pattern may not be officially recommended. |
| "I'll just note it might be outdated" | A disclaimer doesn't help. Either verify and cite, or clearly flag unverified. Hedging is the worst option. |
| "This is simple, no need to check" | Simple wrong patterns become templates. A deprecated Anchor constraint gets copied into ten instructions before anyone notices. |
| "Anchor version doesn't matter much" | Constraint syntax, IDL shape, and macros shifted across Anchor releases. The version is the whole answer. |

## Red Flags

- Writing framework-specific code without checking the docs for that version
- Not reading `Cargo.toml` / `Anchor.toml` / `package.json` before implementing
- Not confirming `@solana/web3.js` v1 vs v2 before writing imports
- "I believe" / "I think" about an API instead of citing the source
- Implementing a pattern without knowing which version it applies to
- Citing Stack Overflow or a blog instead of official docs
- Using a deprecated Anchor/Next/Astro/Tailwind API because it's in training data
- Delivering framework-specific code with no source citations
- Fetching a whole docs site when one page is relevant

## Verification

After implementing with source-driven development:

- [ ] Framework/library versions identified from the manifest (`Cargo.toml`/`Anchor.toml`/`package.json`/`pyproject.toml`)
- [ ] `@solana/web3.js` v1 vs v2 confirmed before any Solana client code
- [ ] Official docs fetched for each framework-specific pattern, pinned to the detected version
- [ ] All sources are official docs — not blog posts, Stack Overflow, or training data
- [ ] Code follows the current version's documented patterns; no deprecated APIs (checked against migration guides)
- [ ] Non-trivial decisions carry source citations with full, deep-linked URLs
- [ ] Conflicts between docs and existing code surfaced to the user
- [ ] Anything unverifiable is explicitly flagged as unverified
- [ ] Then run the Definition of Done gate (`fullstack-standard` → `references/definition-of-done.md`)

## See Also

- `fullstack-standard` — the engineering bar; `references/backend-standards.md` (Anchor/on-chain, `@solana/web3.js`) and `references/frontend-standards.md` (Astro/Next/Tailwind).
- `test-driven-development` — when docs conflict or a version's behavior is unclear, prove which pattern works with a failing-first test.
- `doubt-driven-development` — SDD verifies the API *exists and is current*; doubt-driven verifies you *used it correctly* under the contract.
- `deprecation-and-migration` — when the docs flag a pattern deprecated, that skill governs the migration.
