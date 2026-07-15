---
description: Simplify code for clarity and maintainability — reduce complexity without changing behavior
---

Invoke the `code-simplification` skill.

Simplify recently changed code (or the specified scope) while preserving exact behavior:

1. Read the `fullstack-standard` skill and study project conventions (minimal abstraction, type-driven, match surrounding code)
2. Identify the target code — recent changes unless a broader scope is specified
3. Understand the code's purpose, callers, edge cases, and test coverage before touching it (Chesterton's Fence — don't remove what you don't understand)
4. Scan for simplification opportunities:
   - Deep nesting → guard clauses / early returns
   - Long functions → split by responsibility
   - Speculative abstraction (service/repo/DI layers, needless traits/generics) → inline to the direct path
   - Generic names → descriptive names
   - Duplicated logic → shared function or shared types crate/module
   - Dead code → remove after confirming (git remembers)
5. Apply each simplification incrementally — run tests after each change (`cargo test` / `pytest` / `pnpm test`)
6. Verify all tests pass, it compiles, lint is clean (`cargo clippy -- -D warnings` / `ruff check .` / `pnpm lint`), and the diff is clean

Relocating complexity isn't reducing it. If tests fail after a change, revert it and reconsider. Use `code-review-and-quality` to review the result.
