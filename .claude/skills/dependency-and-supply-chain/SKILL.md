---
name: dependency-and-supply-chain
description: >-
  Manages third-party dependencies as attack surface and liability across the
  eonedge stack — Cargo/crates.io (Rust/Anchor), npm/pnpm (TypeScript), and
  pip/PyPI (Python). Use when adding or upgrading a dependency, reviewing a diff
  that touches a lockfile, reacting to a CVE/RustSec advisory, auditing licenses,
  or hardening CI against supply-chain attacks. Use before a release to run the
  audit gate. Pairs with security-and-hardening for runtime security.
---

# Dependency & Supply-Chain

## Overview

Every dependency is code you didn't write, running with your privileges, plus its
entire transitive tree. It is **attack surface** (typosquats, compromised
maintainers, malicious `postinstall`), **liability** (unmaintained, license
conflict), and **weight** (build time, binary size, on-chain compute). Treat
adding one as a decision, not a reflex; keep what you have pinned, audited, and
minimal.

The on-chain angle matters most: a compromised or unaudited crate in an Anchor
program can drain a treasury. Pin exact versions, prefer audited crates, and read
what you pull in.

## When to Use

- **Adding or upgrading** any dependency (direct or a notable transitive bump).
- **Reviewing** a PR whose diff touches `Cargo.lock`, `pnpm-lock.yaml`,
  `package-lock.json`, `poetry.lock`, or `requirements*.txt`.
- **Reacting** to a security advisory (RustSec, GHSA, CVE) or a `cargo audit` /
  `pnpm audit` / `pip-audit` finding.
- **Before a release** — run the audit gate as part of the pre-ship checklist.
- **Auditing licenses** for compliance.

Runtime input validation, authz, and secret handling defer to
`security-and-hardening`; the pre-ship gate to `fullstack-standard` →
`references/definition-of-done.md`.

## Adding a dependency — the bar

Before `cargo add` / `pnpm add` / `pip install`, justify it in one sentence and
check:

1. **Do we need it?** Prefer the standard library or a crate/package already in
   the tree. A three-line helper beats a new dependency.
2. **Is it maintained?** Recent commits, releases, open-issue responsiveness. An
   abandoned dep is a future migration.
3. **How heavy is the tail?** Look at the *transitive* tree, not just the direct
   add (`cargo tree`, `pnpm why`, `pipdeptree`). One convenience import can pull
   in dozens of crates.
4. **License compatible?** No copyleft creeping into a proprietary program;
   confirm before adding.
5. **Provenance sane?** Correct spelling (typosquat check), reputable
   author/org, download counts consistent with reputation.

## Pin & lock

- **Commit lockfiles** for anything deployed: `pnpm-lock.yaml` /
  `package-lock.json`, `poetry.lock` or fully-pinned `requirements.txt`, and
  `Cargo.lock` for **binaries/programs** (libraries omit it — matches the repo
  `.gitignore`).
- **Pin exact versions** for on-chain crates (`anchor-lang`, `solana-program`,
  `spl-*`). A silent minor bump can change CPI behavior or compute cost.
- **CI installs frozen:** `--locked` (Cargo), `--frozen-lockfile` (pnpm),
  `pip install --require-hashes` / `poetry install --no-update`. A build that can
  silently resolve a new version is not reproducible.

## Audit tooling per stack

### Rust / Anchor / Solana

```bash
cargo audit            # RustSec advisory DB — known-vulnerable crates
cargo deny check       # advisories + licenses + banned/duplicate crates
cargo tree -d          # find duplicate/conflicting versions
```

Keep a `deny.toml` for allowed licenses and banned crates. Pin the Solana/Anchor
toolchain; verify a program's IDL matches the deployed binary before trusting it.

### TypeScript / Node

```bash
pnpm audit --prod              # advisories affecting production deps
osv-scanner --lockfile pnpm-lock.yaml   # cross-ecosystem OSV scan
pnpm why <pkg>                 # trace why a transitive dep is present
```

Distrust `postinstall` scripts; use `--ignore-scripts` where feasible and review
any package that needs one. Watch for lockfile churn that adds unexpected
maintainers or packages.

### Python

```bash
pip-audit                      # PyPI advisory scan
pip-audit -r requirements.txt  # against a pinned file
```

Pin transitive deps (lock or hashes), not just top-level. No `print()` in tooling
— `loguru` (house Python style, `ruff`, line length 100).

## Supply-chain hardening

- **Lockfile diffs are review material.** An unexplained new package or a jump in
  transitive count in a PR is a red flag — ask why before approving.
- **No unvetted install scripts.** `postinstall`/build scripts run arbitrary code
  at install time; prefer packages without them.
- **Typosquat & confusion checks.** Verify the exact name and registry; beware
  internal-looking names that resolve to a public registry (dependency
  confusion).
- **Minimize, then verify.** Fewer deps = smaller attack surface. For the ones you
  keep, prefer versions with published provenance/signatures.
- **Update deliberately.** Let `dependabot`/`renovate` open PRs, but read the
  changelog — never blind-merge a major bump. Security patches first, feature
  bumps on their own schedule.

## CI gate

Run the audit in CI and **fail on high-severity** advisories:

```yaml
# per stack, in the pipeline
- run: cargo audit --deny warnings          # Rust
- run: pnpm audit --prod --audit-level high  # Node
- run: pip-audit                             # Python
```

Wire this into `ci-cd-and-automation`. Treat a new high-severity advisory like a
build break: triage, patch or pin, or document the accepted risk with an owner.

## Reacting to an advisory

1. Confirm exposure: is the vulnerable path actually reachable (`cargo tree` /
   `pnpm why` to the affected version)?
2. Patch to a fixed version; if none exists, pin away from it, apply a
   `[patch]`/override, or vendor a fix.
3. Add a regression note; if a secret or key could have been exposed, rotate it
   and follow `security-and-hardening`.
4. For on-chain code, re-audit the affected instruction paths before redeploying.

## See Also

- `security-and-hardening` — runtime security (hostile input, authz, secrets,
  on-chain account/CPI safety).
- `ci-cd-and-automation` — wiring the audit gate into the pipeline.
- `shipping-and-launch` — the pre-release audit as part of the launch checklist.
