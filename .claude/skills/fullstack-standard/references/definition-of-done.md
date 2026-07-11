# Definition of Done — commands & gate

Run these for real before reporting any nontrivial change as complete. Run the gate
for the layer(s) you touched: **backend** and **frontend** are separate below. A
full-stack change runs both. Copy/paste, observe output, don't guess.

## Backend gate

| # | Check | Rust / Anchor | Server TS | Python |
|---|-------|---------------|-----------|--------|
| 1 | Lint (zero tolerance) | `cargo clippy -- -D warnings` | `pnpm lint` | `ruff check .` |
| 2 | Format | `cargo fmt --check` | `pnpm prettier -c .` | `ruff format --check .` |
| 3 | Types | `cargo check` | `pnpm tsc --noEmit` | type hints + `mypy`/`pyright` if configured |
| 4 | Unit tests (hermetic) | `cargo test` | `pnpm test` | `pytest` |
| 5 | On-chain / integration | `anchor test` (local validator) | integration suite | `pytest tests/integration` |
| 6 | Build | `cargo build --release` | `pnpm build` | `pip install -e .` |

## Frontend gate

| # | Check | Web / Browser TS (Astro / Next / Tailwind) |
|---|-------|--------------------------------------------|
| 1 | Lint (zero tolerance) | `pnpm lint` |
| 2 | Format | `pnpm prettier -c .` |
| 3 | Types | `pnpm tsc --noEmit` |
| 4 | Component/unit tests (hermetic) | `pnpm test` |
| 5 | E2E (if present) | `pnpm e2e` / Playwright |
| 6 | Build | `pnpm build` |
| 7 | Manual pass | loaded the page: responsive, keyboard-navigable, light + dark, no layout shift |

## Non-negotiables beyond the commands

- **Coverage:** every new code path has a test. Aim >80% on new code.
- **Hermetic units:** unit tests touch no network, no live DB, no wall clock they
  don't control. Anything that needs a running service is an *integration* test in
  a separate dir.
- **No warning suppression to pass the gate.** Fixing the code beats `#[allow(...)]`
  / `// eslint-disable` / `# noqa`. If a suppression is truly warranted, add a
  one-line comment explaining why.
- **No `unwrap()`/`expect()`/`any`/`!`/`print()` sneaking into runtime paths.**
  Errors are typed and handled; logging goes through the project logger.
- **Verified end-to-end:** you drove the actual flow (ran the endpoint, loaded the
  page, sent the tx on devnet) — typecheck alone is not verification.
- **Secret scan:** `git diff --staged` reviewed; no keys, tokens, `.env`, seed
  phrases, or private keys in the change. Nothing sensitive shipped to the browser.

## Reporting rule

If the gate is green, state it plainly with the commands you ran. If any row fails
or was skipped, say which and why — never round "6/7 passed" up to "done".
