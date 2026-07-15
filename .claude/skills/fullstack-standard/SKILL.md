---
name: fullstack-standard
description: >-
  The engineering bar for eonedge's fullstack work — apply BEFORE writing,
  refactoring, reviewing, or shipping any code in this workspace. Covers the
  house stack: Rust/Anchor/Solana, TypeScript, Astro/Next + Tailwind, Python.
  Enforces minimal abstraction, type-driven design, strict lint gates,
  conventional commits, hermetic tests, secret hygiene, and deploy discipline.
  Trigger on: implementing a feature, adding a layer/abstraction, opening/reviewing
  a PR, "is this good enough to ship", commit messages, handling secrets/keys,
  or working on a deployed node.
---

# Fullstack Standard

This is the non-negotiable engineering bar for this workspace. Match this bar or
flag explicitly where you fall short — never silently lower it. It is split into
two layers that are kept separate on purpose:

- **Frontend** → `references/frontend-standards.md` (web/UI, browser TypeScript)
- **Backend** → `references/backend-standards.md` (Rust/Anchor/Solana, Python, server TS)

## Core philosophy (read first, every time)

1. **Minimal abstraction — layers must earn their keep.** No service layers, no
   repository pattern, no DI containers unless the code is genuinely simpler
   *with* them. Map requests directly to handlers. Access the DB directly (raw
   `sqlx`). If you introduce an indirection, be ready to justify it in one sentence.

2. **Type-driven design.** Domain types are the contract between modules. Define
   them once in a shared types crate/module; everything depends on it. No
   stringly-typed interfaces, no `any`, no untyped dicts crossing a boundary.
   Make illegal states unrepresentable.

3. **Ship fast, but never below the bar.** Velocity comes from small, correct,
   well-typed increments — not from skipping lint, tests, or review. The gate
   below is what "done" means. Speed is achieved by keeping the gate cheap to pass,
   not by skipping it.

4. **The repo is the source of truth.** Nothing that matters lives only in your
   head, only in a chat, or only on a deployed node. If it isn't committed, it
   doesn't exist.

## Definition of Done — the pre-ship gate

Code is NOT done until every item passes. Run the real commands; do not assume.
Full detail and per-stack commands: **`references/definition-of-done.md`**.

- [ ] **Lint is clean at zero tolerance** — `cargo clippy -- -D warnings`,
      `ruff check .`, `pnpm lint`. Warnings are errors.
- [ ] **Types check** — `cargo check`, `tsc --noEmit`, no `any`/`unwrap()` in
      non-test paths without a comment justifying it.
- [ ] **Tests pass and are hermetic** — new code has tests; unit tests hit no
      network/DB; integration tests live separately. Aim >80% on new code.
- [ ] **No secrets in the diff** — no keys, tokens, `.env`, or private material.
- [ ] **Formatted** — `cargo fmt`, `prettier`/formatter run.
- [ ] **Verified end-to-end** — you actually exercised the change, not just typecheck.
- [ ] **Conventional commit** — see below.

If any item can't pass, say so plainly and stop — do not report "done".

## Stack-specific standards

Frontend and backend are documented separately — read the one you're touching.
Full-stack changes read both.

### Backend — `references/backend-standards.md`

- **Rust / Anchor / Solana** — `clippy -D warnings`; no `unwrap()`/`expect()` in
  runtime paths (return typed errors, e.g. `thiserror`); on-chain: PDAs for
  identity/treasury, check every account constraint, never trust client input,
  handle rent/CPI/signer checks explicitly. `anchor test` against a local validator.
- **Server TypeScript** — `strict: true`, no `any`, no non-null `!` to dodge the
  checker. Types are the API contract exposed to the frontend. `@solana/web3.js` typed.
- **Python** — PEP 8 via `ruff`, line length 100, type hints required on public
  functions, Google-style docstrings, **no `print()` — use `loguru`**.

### Frontend — `references/frontend-standards.md`

- **Web (Astro 5 / Next 15 / Tailwind v4)** — static-first where possible; server
  components by default; no client JS you don't need. Accessible, responsive,
  works in light+dark. One clear CTA per marketing page.
- **Browser TypeScript** — `strict: true`, no `any`; consume the backend's exported
  types, never redefine API shapes on the client.

## Git & commit discipline

- Branch names: `feat/`, `fix/`, `docs/`, `chore/`, `refactor/`, `test/`.
- **Conventional Commits**: `type(scope): description`. Types: `feat`, `fix`,
  `docs`, `style`, `refactor`, `test`, `chore`. Squash and merge.
- Never commit to the default branch directly; branch first.
- Commit/push only when the user asks.

## Security & secrets hygiene

- Never write secrets into code, configs tracked by git, issues, or logs. Use
  `.env` (gitignored) or a secret manager; reference by env var.
- Security issues go to `SECURITY.md` channels, never a public issue.
- If you spot a leaked/committed credential, flag it and recommend rotation
  immediately — do not just work around it.

## Deploy / node discipline (critical)

Most GPU/compute nodes use **ephemeral container storage** — code that lives only
on a node is lost on restart/redeploy. After ANY work directly on a deployed node,
before stopping or redeploying it:

1. `git status` / `git diff` on the node checkout.
2. Commit to a branch and push, or copy the file back to the local repo and commit.
3. Confirm `git status` is clean on the node.

## How to use this skill

- **Before writing code:** re-read Core Philosophy; pick the minimal design.
- **While coding:** keep types at boundaries; resist premature abstraction.
- **Before saying "done":** run the Definition-of-Done gate for real.
- **On review:** reject anything that fails the gate or violates the philosophy;
  call out over-abstraction and stringly-typed code specifically.
