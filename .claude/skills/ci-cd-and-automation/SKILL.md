---
name: ci-cd-and-automation
description: Sets up and maintains GitHub Actions pipelines that enforce eonedge's Definition-of-Done gate on every change across the polyglot stack — Rust/Anchor (clippy, cargo test, anchor test), Python (ruff, pytest), TypeScript/Astro/Next (pnpm lint, tsc, test, build). Use when creating or modifying a CI pipeline, automating quality gates, configuring test runners in CI, wiring branch protection, or establishing deployment and rollback strategies. Use when a change should trigger automated verification, or when debugging a CI failure.
---

# CI/CD and Automation

## Overview

CI is the machine that runs the Definition-of-Done gate on every single change so
no human and no agent can quietly skip it. It is the enforcement arm of every
other skill in this workspace: the same commands you run locally
(`fullstack-standard` → `references/definition-of-done.md`), run again on neutral
hardware, blocking merge until they pass. **The gate is not advice; CI makes it a
wall.**

Two laws drive the design:

- **Shift left.** Catch a problem at the earliest, cheapest stage. A clippy warning
  caught in CI costs seconds; the same bug caught on devnet costs an afternoon;
  on-chain in production it can cost funds. Static checks before tests, unit tests
  before on-chain tests, on-chain tests before deploy.
- **Faster is safer.** Small, frequent releases reduce risk. A deploy with 3
  changes is trivially debuggable; one with 30 is an investigation. Frequency
  builds confidence in the release process itself.

## When to Use

- Standing up a new project's CI pipeline (Rust workspace, Anchor program, Python
  service, or Astro/Next frontend).
- Adding or modifying automated checks; wiring branch protection.
- Configuring deployment, preview, and rollback pipelines.
- Making a change trigger automated verification.
- Debugging a CI failure and feeding it back to the agent.

**When NOT to use:** defining *what* "done" means — that's `fullstack-standard`.
This skill wires those commands into Actions; it does not redefine the bar.

## The Quality Gate Pipeline

Every change runs the same gate CI that a human runs locally — nothing is
CI-only-special except where noted. This is the full-stack shape; a backend-only
or frontend-only repo runs only its half.

```
Pull Request Opened / push to default branch
    │
    ▼
┌────────────────────────────────────────────────────────┐
│  BACKEND (Rust/Anchor)      BACKEND (Python)   FRONTEND │
│  ─────────────────────      ───────────────    ──────── │
│  cargo clippy -D warnings   ruff check .        pnpm lint       │
│      ↓                          ↓                   ↓    │
│  cargo fmt --check          ruff format --check pnpm prettier -c│
│      ↓                          ↓                   ↓    │
│  cargo check                mypy/pyright         pnpm tsc --noEmit│
│      ↓                          ↓                   ↓    │
│  cargo test                 pytest               pnpm test      │
│      ↓                          ↓                   ↓    │
│  anchor test (validator)    pytest tests/integration  pnpm e2e  │
│      ↓                          ↓                   ↓    │
│  cargo build --release      pip install -e .     pnpm build    │
└────────────────────────────────────────────────────────┘
    │  all green
    ▼
  Ready for review → squash-merge
```

**No gate is skippable.** If clippy fails, fix the code — do not add `#[allow(...)]`
to pass. If a test fails, fix the code — do not `#[ignore]` it or delete the
assertion. Suppression to make CI green is the exact failure mode CI exists to
prevent. A warranted suppression carries a one-line comment explaining why.

## GitHub Actions — backend

### Rust workspace + Anchor program

Anchor tests need a local `solana-test-validator` and the Anchor/Solana
toolchains, so on-chain tests run in their own job. Keep the fast static checks in
a separate, quick job so feedback arrives early (shift left).

```yaml
# .github/workflows/ci-rust.yml
name: CI (rust)
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  static:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with:
          components: clippy, rustfmt
      - uses: Swatinem/rust-cache@v2
      - run: cargo fmt --all --check
      - run: cargo clippy --all-targets -- -D warnings   # warnings ARE errors
      - run: cargo check --all-targets

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - uses: Swatinem/rust-cache@v2
      - run: cargo test --all                            # hermetic unit tests

  anchor:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - uses: Swatinem/rust-cache@v2
      - name: Install Solana + Anchor
        run: |
          sh -c "$(curl -sSfL https://release.anza.xyz/stable/install)"
          echo "$HOME/.local/share/solana/install/active_release/bin" >> "$GITHUB_PATH"
          cargo install --git https://github.com/coral-xyz/anchor avm --locked
          avm install latest && avm use latest
      - name: anchor test
        run: anchor test          # spins up a local validator, runs on-chain suite
```

`anchor test` exercises the **failure** cases — bad signer, wrong PDA, insufficient
funds — not just the happy path. If those aren't in the suite, the pipeline is
green but the program is unverified.

### Python service

```yaml
# .github/workflows/ci-python.yml
name: CI (python)
on:
  pull_request: { branches: [main] }
  push: { branches: [main] }

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12', cache: 'pip' }
      - run: pip install -e '.[dev]'
      - run: ruff check .
      - run: ruff format --check .
      - run: pyright         # or mypy, if that's what the repo configures
      - run: pytest          # hermetic units: no live network/DB

  integration:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: testdb
          POSTGRES_USER: ci_user
          POSTGRES_PASSWORD: ${{ secrets.CI_DB_PASSWORD }}   # never hardcode, even for CI
        ports: [ '5432:5432' ]
        options: >-
          --health-cmd pg_isready --health-interval 10s
          --health-timeout 5s --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12', cache: 'pip' }
      - run: pip install -e '.[dev]'
      - run: pytest tests/integration
        env:
          DATABASE_URL: postgresql://ci_user:${{ secrets.CI_DB_PASSWORD }}@localhost:5432/testdb
```

> Even a throwaway CI database uses a GitHub Secret for its credential — never a
> literal in the workflow. Config and secrets come from the environment, always.

Backend rules this enforces live in `fullstack-standard` →
`references/backend-standards.md`.

## GitHub Actions — frontend

Static-first Astro / Next + Tailwind. Split fast jobs so lint/type feedback lands
before the slower build and e2e.

```yaml
# .github/workflows/ci-web.yml
name: CI (web)
on:
  pull_request: { branches: [main] }
  push: { branches: [main] }

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with: { node-version: '22', cache: 'pnpm' }
      - run: pnpm install --frozen-lockfile
      - run: pnpm lint
      - run: pnpm prettier -c .
      - run: pnpm tsc --noEmit          # strict: true, no any, no !
      - run: pnpm test                  # hermetic component/unit tests
      - run: pnpm build

  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with: { node-version: '22', cache: 'pnpm' }
      - run: pnpm install --frozen-lockfile
      - run: pnpm exec playwright install --with-deps chromium
      - run: pnpm build
      - run: pnpm e2e
      - uses: actions/upload-artifact@v4
        if: failure()
        with: { name: playwright-report, path: playwright-report/ }
```

Frontend rules this enforces live in `fullstack-standard` →
`references/frontend-standards.md`. The manual pass (responsive, keyboard-navigable,
light + dark, no layout shift) is human — CI can't fully replace it; preview
deployments (below) are where it happens.

## Feeding CI Failures Back to the Agent

The point of CI with agents is the tight feedback loop. When CI fails, reproduce
it locally first, then fix — never push blind to see if the next run is greener.

```
CI fails → copy the exact failure → reproduce locally → fix → re-run gate locally → push
```

| Failure | Agent response |
|---|---|
| `clippy -D warnings` / `ruff` | Fix the code. Do NOT add `#[allow]` / `# noqa` to pass. |
| Type error (`cargo check` / `tsc` / pyright) | Read the error location, narrow the type properly. No `any`, no `!`, no `unwrap()`. |
| `cargo test` / `pytest` / `pnpm test` fail | Follow `debugging-and-error-recovery`. Fix the code, not the test. |
| `anchor test` fails | Reproduce against a local `solana-test-validator`; check account constraints, seeds, bump, rent. |
| Build error | Check config, deps, lockfile drift. |
| Flaky test | Fix the flakiness. Re-running is not a fix — a flaky test masks a real bug. |

## Deployment Strategies

### Preview deployments

Every PR gets a preview so the human manual pass (light/dark, responsive,
keyboard) can happen on the real thing before merge. On-chain equivalent: deploy
the program to **devnet** and run the SDK against it — never let production/mainnet
be the first place a program version runs.

### Feature flags — deploy ≠ release

Flags decouple shipping code from turning it on. Prefer a flag over a long-lived
branch (see `git-workflow-and-versioning`).

```typescript
// strict, typed flag check — consume the flag type, don't stringly-type it
if (featureFlags.isEnabled("new-settlement-path", { userId })) {
  return renderNewSettlement();
}
return renderLegacySettlement();
```

- Ship code to main behind a flag, enable when ready.
- Roll back by flipping the flag, not by reverting and redeploying.
- Canary: 1% → 10% → 100%.

**Flag lifecycle:** create → test → canary → full rollout → **remove the flag and
the dead branch of code**. Flags that live forever are debt with a cleanup date of
"never" — set a real one when you create it. Removing a retired flag path is a
`deprecation-and-migration` job.

### Staged rollout + rollback

```
merge → staging/devnet (auto) → manual verification →
production/mainnet (manual trigger) → monitor 15-min window →
   errors? → rollback     clean? → done
```

Every deploy is reversible. For services, keep a `workflow_dispatch` rollback that
redeploys a previous **tag** (tags come from `git-workflow-and-versioning`). For an
on-chain program, "rollback" is a governed upgrade back to the prior verified
build — plan the upgrade path *before* deploying, and for a breaking state change
follow `deprecation-and-migration`. Programs deployed as immutable can't be rolled
back at all: verify on devnet exhaustively first.

## Automation Beyond CI

### Dependabot

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: cargo
    directory: /
    schedule: { interval: weekly }
    open-pull-requests-limit: 5
  - package-ecosystem: npm            # pnpm workspaces
    directory: /
    schedule: { interval: weekly }
  - package-ecosystem: pip
    directory: /
    schedule: { interval: weekly }
  - package-ecosystem: github-actions
    directory: /
    schedule: { interval: weekly }
```

### Branch protection (required)

- **Required status checks:** every gate job above must pass before merge.
- **No direct pushes / force-pushes to the default branch.** Branch, then
  squash-merge (matches `git-workflow-and-versioning`).
- **Keep the build green.** A red default branch blocks everyone — whoever's change
  broke it fixes or reverts it now, not "later".
- **Auto-merge** once checks pass, for low-risk changes behind flags.

## CI Optimization

When the pipeline drifts past ~10 minutes, apply in order of impact:

```
Slow CI?
├── Cache deps        → Swatinem/rust-cache, setup-node/setup-python cache
├── Parallelize       → separate jobs for static / test / anchor / build (already split above)
├── Run only what changed → path filters: skip the web job on a program-only PR
├── Shard             → matrix-split large test suites across runners
├── Prune the critical path → move slow, rarely-breaking tests to a nightly schedule
└── Bigger runners    → for cargo/anchor CPU-heavy builds
```

The Rust cache (`Swatinem/rust-cache`) is the single biggest win on this stack —
uncached `cargo build`/`anchor` is minutes of recompilation every run.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "CI is too slow" | Optimize it (cache, parallelize, shard) — don't skip it. A cached Rust build is minutes; a bad on-chain deploy is funds. |
| "This change is trivial, skip CI" | Trivial changes break builds. CI is fast for trivial changes anyway. |
| "Just add `#[allow]` / `# noqa` to get green" | That's defeating the gate CI exists to enforce. Fix the code; suppress only with a justifying comment. |
| "The test is flaky, re-run it" | Flakiness masks real bugs and burns everyone's time. Fix the flake. |
| "We'll add CI later" | Projects without CI accumulate broken states silently. Wire it on day one. |
| "It passed unit tests, ship the program" | Unit tests aren't `anchor test`. Deploy to devnet and run the failure cases first. |
| "Manual testing is enough" | Manual doesn't scale or repeat. Automate the gate; reserve humans for the light/dark manual pass. |

## Red Flags

- No CI pipeline, or CI that doesn't run the full Definition-of-Done gate.
- Any gate command missing: `clippy -D warnings`, `anchor test`, `ruff`, `pnpm tsc`, `pnpm build`.
- `#[allow]` / `#[ignore]` / `# noqa` / `eslint-disable` added to make CI pass.
- CI failures ignored, silenced, or fixed by re-running.
- Program deployed to mainnet without a devnet run first; no rollback/upgrade plan.
- Secrets hardcoded in a workflow file instead of GitHub Secrets.
- Feature flags with no cleanup date; long CI times with no optimization effort.
- Direct/force pushes to the default branch; no required status checks.

## Verification

After setting up or modifying CI:

- [ ] Every layer touched runs its full gate: lint (`-D warnings`) → format → types → unit → integration/`anchor test`/e2e → build.
- [ ] Pipeline runs on every PR and on push to the default branch.
- [ ] Branch protection makes failures block merge; no direct/force pushes to default.
- [ ] `anchor test` runs against a real local validator and covers failure cases (bad signer, wrong PDA, rent).
- [ ] CI results feed back into the agent loop; suppressions/re-runs are not used to pass.
- [ ] All secrets come from GitHub Secrets, never workflow literals.
- [ ] Deploy path has preview (devnet/staging) + a rollback or governed-upgrade plan; feature flags have cleanup dates.
- [ ] Caching in place; pipeline runs in a reasonable time (Rust cache enabled).

## See Also

- `fullstack-standard` — defines the gate CI enforces. Commands: `references/definition-of-done.md`; backend/frontend rules in the sibling reference files.
- `git-workflow-and-versioning` — branch protection, squash-merge, tags that rollback/deploy consume, feature-flags-over-branches.
- `deprecation-and-migration` — removing retired feature-flag paths; governed upgrade of a deployed program version.
- `debugging-and-error-recovery` — the loop for fixing a failing test surfaced by CI.
