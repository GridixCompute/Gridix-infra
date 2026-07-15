---
name: security-and-hardening
description: Hardens code against attackers across the eonedge stack — Anchor/Solana programs, Rust/Python/TS servers, and the Astro/Next browser. Use when handling untrusted input, authentication/authorization, signer/authority or account-constraint checks, PDA/treasury logic, CPI calls, secrets/keys, or external integrations. Use when building any on-chain instruction, API route, or feature that accepts data you don't control, moves value, or touches keys. Use when reviewing a diff for spoofing, tampering, privilege escalation, or secret leakage.
---

# Security and Hardening

## Overview

Security-first development across a polyglot, on-chain stack. Treat every external input as hostile — an HTTP body, a form field, **and every account and instruction argument a Solana client hands your program**. Treat every secret and keypair as sacred, and every authority/authorization check as mandatory. On-chain there is no "fix it later": a deployed program handles adversarial input on a public ledger from block one, and value is irreversible. Security isn't a phase — it's a constraint on every line that touches untrusted data, signers, or money. **Assume the client is an attacker.**

## When to Use

- Writing or changing any Anchor instruction — signer, authority, PDA, CPI, or lamport movement
- Building anything that accepts input you don't control (API route, form handler, webhook, queue message, LLM output)
- Implementing authentication or authorization (server or on-chain)
- Storing, transmitting, or logging sensitive data or keys
- Integrating external APIs, RPC endpoints, or third-party services
- Adding file uploads, callbacks, or server-side URL fetches
- Reviewing a diff for the STRIDE threats below

**When NOT to use:** pure styling, copy, or non-security refactors with no new trust boundary. But if a change adds a boundary — a new account, a new input, a new external call — it's in scope.

## Process: Threat Model First

Controls bolted on without a threat model are guesses. Before hardening, spend five minutes as the attacker.

1. **Map the trust boundaries.** Where does untrusted data cross in? On the backend: HTTP requests, webhooks, queues, third-party APIs, RPC responses, and **LLM output**. On-chain: **every account passed to an instruction, every instruction argument, and every CPI return**. In the browser: nothing shipped there is trusted — it's all public and user-controlled.
2. **Name the assets.** Credentials, upgrade authority, treasury/mint authority, PDAs that gate funds, PII, RPC keys, signing keypairs. On Solana the highest-value asset is usually *authority over lamports or a mint*.
3. **Run STRIDE over each boundary** — a quick lens, not ceremony:

| Threat | Ask | Web/server mitigation | On-chain (Anchor) mitigation |
|---|---|---|---|
| **S**poofing | Can someone impersonate a user/authority? | AuthN, signature verification | `Signer` check; `has_one`; verify the caller is the expected authority, not a client-supplied pubkey |
| **T**ampering | Can data be altered? | Parameterized queries, HTTPS, integrity checks | `owner` check (account owned by your program); `seeds`+`bump` so a PDA can't be substituted |
| **R**epudiation | Can an action be denied later? | Audit logging of security events | Emit events / record state on-chain where the design calls for it |
| **I**nformation disclosure | Can data leak? | Encryption, field allowlists, generic errors | Nothing on-chain is private — never store secrets or PII in accounts |
| **D**enial of service | Can it be overwhelmed? | Rate limiting, input caps, timeouts | Compute-budget bounds, account-size caps, reject unbounded loops over client vecs |
| **E**levation of privilege | Can a user gain rights they shouldn't? | AuthZ checks, least privilege | Missing signer/`has_one`/`owner` check is privilege escalation — the #1 Solana bug class |

4. **Write abuse cases next to use cases.** For every instruction and endpoint, ask "how do I misuse this?" — pass the wrong account, a PDA I control, an unsigned authority, a duplicate account, a closed account reopened — then make that your **first test** (`anchor test` failure cases, not just the happy path).

If you can't name the trust boundaries for a feature, you're not ready to secure it. This is OWASP **A04: Insecure Design** — most breaches begin in design, not code.

## The Three-Tier Boundary System

### Always Do (No Exceptions)

**On-chain (Anchor / Solana):**
- **Validate EVERY account constraint** — `has_one`, `seeds`, `bump`, `owner`, and `Signer`. An unchecked account is an exploit.
- **Derive identity/treasury as PDAs**; never accept a client-supplied address where a PDA is expected. Re-derive and compare; don't trust the passed key.
- **Verify the signer is the authority** the operation requires — not merely that *a* signature exists.
- **Handle rent, CPI, and lamport math explicitly.** Check balances before transfer; use checked arithmetic (`checked_add`/`checked_sub`) — an overflow is a mint.
- **Validate CPI targets and return data**; a CPI into an attacker-controlled program is code execution in your context.

**Server (Rust / Python / TS):**
- **Validate all external input** at the boundary. No `unwrap()`/`expect()` on untrusted data — return typed errors (`thiserror`, `?`).
- **Parameterize all DB queries** (`sqlx` bind params) — never format user input into SQL.
- **HTTPS everywhere**; hash passwords with argon2/scrypt/bcrypt; sessions in `httpOnly, secure, sameSite` cookies.
- **Secrets from env only** (`.env` gitignored). Run `cargo audit` / `pip-audit` / `pnpm audit` before release.

**Browser (Astro / Next):**
- **Encode output** — rely on framework auto-escaping; never bypass it with raw HTML injection.
- **Set security headers** (CSP, HSTS, X-Frame-Options, X-Content-Type-Options).

### Ask First (Requires Human Approval)

- Changing signer/authority logic, PDA seeds, or upgrade authority on a deployed program
- Adding or changing a CPI target, or granting a program new authority over funds/mints
- New authentication flows or auth-logic changes
- Storing new categories of sensitive data (PII, payment info)
- New external service/RPC integrations, or changing CORS config
- Adding file upload handlers or server-side URL fetches
- Modifying rate limiting or granting elevated roles

### Never Do

- **Never trust a client-supplied pubkey where a PDA or known authority belongs.**
- **Never skip an account constraint "because the client is ours"** — the client is public; anyone can craft a transaction.
- **Never ship a secret, private key, or seed phrase to the browser** — everything in client code is public. Public keys and public RPC endpoints only.
- **Never commit secrets** (keys, tokens, keypairs, `.env`) to git.
- **Never log secrets, tokens, private keys, or full PII.**
- **Never use unchecked arithmetic on lamports/token amounts.**
- **Never expose stack traces or internal errors** to users.
- **Never trust client-side validation** as a security boundary.

## On-Chain Prevention Patterns (Anchor)

The dominant Solana vulnerability classes are **missing ownership/signer checks, account substitution, and unchecked arithmetic.** Let Anchor's constraint system do the work — and verify it did.

```rust
// BAD: account substitution + missing authority check.
// `authority` is just a pubkey the client passed; `vault` isn't tied to anything.
#[derive(Accounts)]
pub struct Withdraw<'info> {
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    pub authority: AccountInfo<'info>, // unchecked, unsigned — anyone can pass any key
}

// GOOD: signer proven, vault bound to its authority by PDA + has_one.
#[derive(Accounts)]
pub struct Withdraw<'info> {
    #[account(
        mut,
        seeds = [b"vault", authority.key().as_ref()],
        bump = vault.bump,          // stored bump, not client-supplied
        has_one = authority,        // vault.authority MUST equal the signer below
    )]
    pub vault: Account<'info, Vault>,
    pub authority: Signer<'info>,   // must actually sign
}
```

```rust
// Lamport math: checked, and never trust the client-passed amount blindly.
let new_balance = vault
    .balance
    .checked_sub(amount)
    .ok_or(VaultError::InsufficientFunds)?; // typed error, not unwrap()
require!(amount > 0, VaultError::ZeroAmount);
```

**Checklist for every instruction:** Is every account's `owner` verified? Does every authority `Signer`? Are PDAs re-derived with `seeds`+`bump` (not passed in)? Is `has_one` wiring each account to its parent? Are duplicate-account and closed-account attacks handled? Is all arithmetic checked? Test each of these as a **failing** `anchor test` case. Full rules: `fullstack-standard` → `references/backend-standards.md`.

## Server Prevention Patterns

### Injection — parameterize, never concatenate

```rust
// Rust / sqlx — bind params, never format! user input into SQL
let user = sqlx::query_as!(User, "SELECT * FROM users WHERE id = $1", user_id)
    .fetch_optional(&pool)
    .await?;
```

### Broken access control — check authorization, not just authentication

```rust
// Axum: authenticate AND verify ownership of the resource
let task = tasks::find_by_id(&pool, task_id).await?
    .ok_or(ApiError::NotFound)?;
if task.owner_id != auth.user_id {
    return Err(ApiError::Forbidden); // typed error -> generic response
}
```

### Input validation at the boundary

```typescript
// Server TS: validate untrusted input into a typed shape at the edge.
// Types are the contract the frontend imports — validate what crosses the wire.
import { z } from 'zod';

const CreateTask = z.object({
  title: z.string().min(1).max(200).trim(),
  priority: z.enum(['low', 'medium', 'high']).default('medium'),
});

const parsed = CreateTask.safeParse(body);
if (!parsed.success) return json(422, { error: { code: 'VALIDATION_ERROR' } });
// parsed.data is now typed and safe
```

```python
# Python: validate at the boundary; type hints required on public fns.
from pydantic import BaseModel, Field

class CreateTask(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    priority: Literal["low", "medium", "high"] = "medium"
```

### Sensitive data & secrets

```rust
// Secrets from env, never literals. Fail closed if missing.
let rpc_key = std::env::var("HELIUS_API_KEY")
    .map_err(|_| ConfigError::MissingSecret("HELIUS_API_KEY"))?;
```

Exclude sensitive fields from any API response (return a public projection type, not the DB row). PII encrypted at rest where it applies.

### SSRF — allowlist any server-side URL fetch

Any time the server fetches a URL the user influenced — webhooks, "import from URL", image proxy, RPC override — an attacker aims it at internal services (cloud metadata `169.254.169.254`, `localhost`, private IPs). Allowlist scheme + host, reject if any resolved IP is private/reserved, and forbid redirects. **TOCTOU caveat:** DNS is re-resolved on connect, so a short-TTL record can rebind to an internal IP between check and fetch — for high-risk surfaces resolve once and connect to the pinned IP, or put a filtering agent in front.

## Secrets & Key Management

```
.env.example  → committed (placeholders only)
.env          → NEVER committed (real secrets)
Solana keypairs (*.json), *.pem, *.key → NEVER committed
```

`.gitignore` must include `.env`, `.env.*.local`, `*.pem`, `*.key`, and any keypair JSON. Before committing:

```bash
git diff --cached | grep -iE "password|secret|api_key|private_key|[0-9]{2,},[0-9]{2,}" # last pattern catches raw keypair byte arrays
```

**If a secret or keypair ever reaches a remote, it's compromised — rotate it.** Revoke and reissue (and for a signing key, move funds/authority) *first*, then purge history. Deleting the line is not enough.

## Securing AI / LLM Features

If a service calls an LLM — agent, summarizer, RAG — map it to the OWASP Top 10 for LLM Applications:

- **Treat all model output as untrusted input (LLM05).** Never pass it into SQL, a shell, `eval`, `innerHTML`, a file path, or an on-chain instruction unvalidated. Validate and encode it exactly like raw user input.
- **Assume prompts can be hijacked (LLM01).** Untrusted text in the context can carry instructions. The system prompt is not a security boundary — enforce permissions in code.
- **Keep secrets, keypairs, and other users' data out of prompts (LLM02/07).** Anything in context can be echoed back.
- **Constrain tool/agent permissions (LLM06).** Scope to the minimum; require confirmation for destructive or irreversible actions (especially anything that signs or moves funds); validate every tool argument.
- **Bound consumption (LLM10).** Cap tokens, request rate, and loop depth.

```typescript
// GOOD: model output is data — parse defensively, validate against a schema, then act
let intent;
try {
  intent = CommandSchema.parse(JSON.parse(await llm.replyJson(userMessage)));
} catch {
  throw new ValidationError('unexpected model output');
}
await runAllowlistedAction(intent.action, intent.params); // never eval/sign raw model text
```

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The client is ours, it won't pass a bad account" | The client is public code and the chain is open. Anyone crafts their own transaction. Validate every account. |
| "Anchor checks accounts for me" | Only the constraints you *write* (`has_one`, `seeds`, `owner`, `Signer`) are checked. A missing one is an open door. |
| "It's just devnet / a prototype" | Prototypes become mainnet. On-chain habits from day one — the ledger is unforgiving and irreversible. |
| "We'll add the signer check later" | "Later" is after someone drains the vault. Authorization is not a follow-up ticket. |
| "This is an internal tool, security doesn't matter" | Internal tools get compromised. Attackers target the weakest link. |
| "No one would try to exploit this" | Automated scanners and MEV bots find it in minutes. Obscurity is not security. |
| "The framework handles security" | Frameworks provide tools, not guarantees. You must use them correctly. |
| "It's just LLM output, it's only text" | That text can be SQL, a shell command, or a transaction. Treat it as untrusted input. |
| "Overflow won't happen with these numbers" | Attacker-chosen amounts make it happen. Use checked arithmetic — an overflow is a mint. |

## Red Flags

- An Anchor account with no `owner`/`seeds`/`has_one`/`Signer` constraint
- A client-supplied `Pubkey` used where a PDA should be re-derived
- Unchecked arithmetic (`+`/`-`) on lamports or token amounts
- `unwrap()`/`expect()` on data that came from a client or RPC
- A CPI into a program address the client controls
- Secrets, keypairs, or seed phrases in source, logs, or client-shipped code
- User input concatenated into SQL, a shell, or HTML
- API endpoints without authorization (ownership) checks — not just authentication
- Wildcard (`*`) CORS, no rate limiting on auth endpoints
- Stack traces or internal errors returned to users
- Server fetches a user-supplied URL with no allowlist (SSRF)
- LLM/model output passed into a query, the DOM, a shell, `eval`, or a transaction
- Dependencies with known critical vulnerabilities (`cargo audit`/`pip-audit`/`pnpm audit`)

## Verification

- [ ] **On-chain:** every instruction's accounts have the right `owner`/`seeds`/`bump`/`has_one`/`Signer` constraints, verified by **failing** `anchor test` cases (bad signer, wrong PDA, substituted account, insufficient funds)
- [ ] All lamport/token arithmetic uses checked ops; no `unwrap()`/`expect()` on untrusted data
- [ ] No client-supplied address is trusted where a PDA/known authority is required
- [ ] All external input validated at the boundary (server + on-chain)
- [ ] Authorization (ownership), not just authentication, checked on every protected path
- [ ] SQL parameterized; output encoded; SSRF-prone fetches allowlisted
- [ ] `cargo audit` / `pip-audit` / `pnpm audit` show no critical/high vulns
- [ ] No secrets, keypairs, or PII in source, git history, logs, or client bundle (`git diff --staged` reviewed; nothing sensitive shipped to the browser)
- [ ] Security headers present; CORS restricted to known origins; auth endpoints rate-limited
- [ ] LLM/model output validated and encoded before any use (if AI features present)

Then run the full **Definition of Done** gate: `fullstack-standard` → `references/definition-of-done.md`.

## See Also

- **`fullstack-standard`** — the engineering bar; `references/backend-standards.md` for the Anchor/on-chain rules this skill enforces, plus the secret-hygiene section.
- Sibling skills: **`observability-and-instrumentation`** (never log secrets; audit-log security events), **`test-driven-development`** (write the abuse case as a failing test first), **`debugging-and-error-recovery`** (when a check fails in the wild).
