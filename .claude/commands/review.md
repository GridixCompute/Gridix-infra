---
description: Conduct a five-axis code review — correctness, readability, architecture, security, performance
---

Invoke the `code-review-and-quality` skill.

Review the current changes (staged or recent commits) across all five axes:

1. **Correctness** — Matches the spec? Edge cases and error paths handled? Tests adequate? For on-chain: are all account constraints (`has_one`, `seeds`, `bump`, `owner`, signer) validated?
2. **Readability** — Clear names? Straightforward logic? Well-organized? No stringly-typed interfaces?
3. **Architecture** — Follows existing patterns? Minimal abstraction (no service/repo/DI layer that doesn't earn its keep)? Types at boundaries? Right direction of dependencies?
4. **Security** — Input validated at boundaries? Secrets kept out of code/logs/browser? On-chain: hostile-client assumptions, PDA integrity, CPI/rent/signer safety? (Use `security-and-hardening`)
5. **Performance** — No N+1 or unbounded ops? Solana compute-unit budget sane? Core Web Vitals for web? (Use `performance-optimization`)

Categorize findings as Critical, Important, or Suggestion, with `file:line` references and fix recommendations. The exit bar is the Definition of Done gate. Call out over-abstraction and stringly-typed code specifically.
