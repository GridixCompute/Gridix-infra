---
description: Run the pre-launch checklist via parallel fan-out to specialist personas, then synthesize a go/no-go decision
---

Invoke the `shipping-and-launch` skill.

`/ship` is a **fan-out orchestrator**. It runs three specialist personas in parallel against the current change, then merges their reports into a single go/no-go decision with a rollback plan. The personas operate independently — no shared state, no ordering.

## Phase A — Parallel fan-out

Spawn three subagents concurrently using the Agent tool. **Issue all three Agent tool calls in a single assistant turn so they execute in parallel** — sequential calls defeat the purpose.

Each call passes `subagent_type` matching the persona's `name`:

1. **`code-reviewer`** — Five-axis review (correctness, readability, architecture, security, performance) on the staged changes or recent commits. Output the standard review template.
2. **`security-auditor`** — Vulnerability + threat-model pass: on-chain (PDA/signer/authority/account-constraint/CPI/rent), OWASP Top 10, secrets handling, auth/authz, dependency CVEs. Output the standard audit report.
3. **`test-engineer`** — Coverage analysis: gaps in happy path, edge cases, error paths, on-chain failure cases, concurrency. Output the standard coverage analysis.

Constraints (Claude Code subagent model):
- Subagents cannot spawn other subagents — no persona delegates to another.
- Each subagent gets its own context window and returns only its report.

**Persona resolution.** User-level `.claude/agents/` definitions take precedence over any plugin versions.

## Phase B — Merge in main context

Once all three reports are back, the main agent (not a sub-persona) synthesizes them:

1. **Code Quality** — Aggregate Critical/Important findings + any failing lint/test/build (`cargo clippy -- -D warnings`, `cargo test`, `anchor test`, `ruff check .`, `pnpm lint`, `pnpm tsc --noEmit`, `pnpm build`). Resolve duplicates.
2. **Security** — Promote Critical/High `security-auditor` findings to blockers. On-chain findings are blockers by default.
3. **Performance** — From `code-reviewer`'s perf axis; Solana compute budget; Core Web Vitals if web-facing.
4. **Accessibility** — Keyboard nav, screen reader, contrast, light+dark (handle directly).
5. **Infrastructure** — Env vars, migrations, monitoring, feature flags; **ephemeral node discipline** (code on a deployed node is committed & pushed before redeploy).
6. **Documentation** — README, ADRs, changelog.

## Phase C — Decision and rollback

```markdown
## Ship Decision: GO | NO-GO

### Blockers (must fix before ship)
- [Source persona: Critical finding + file:line]

### Recommended fixes (should fix before ship)
- [Source persona: Important finding + file:line]

### Acknowledged risks (shipping anyway)
- [Risk + mitigation]

### Rollback plan
- Trigger conditions: [signals that would prompt rollback]
- Rollback procedure: [exact steps — for on-chain, the program-upgrade/authority path]
- Recovery time objective: [target]

### Specialist reports (full)
- [code-reviewer / security-auditor / test-engineer reports]
```

## Rules

1. The three Phase A personas run in parallel — never sequentially.
2. Personas do not call each other. The main agent merges in Phase B.
3. The rollback plan is mandatory before any GO.
4. Any Critical finding → default verdict NO-GO unless the user explicitly accepts the risk.
5. **Skip the fan-out only if all are true:** the change touches ≤2 files, the diff is <50 lines, and it does not touch on-chain programs, keys/authority, auth, payments, data access, or config/env. Otherwise default to fan-out.
