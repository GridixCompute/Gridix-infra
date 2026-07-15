---
description: Start spec-driven development — write a structured spec before writing code
---

Invoke the `spec-driven-development` skill.

Begin by understanding what the user wants to build. Ask clarifying questions about:
1. The objective and target users
2. Core features and acceptance criteria
3. Which part of the stack it touches — on-chain (Anchor/Solana), backend (Rust/Python server), frontend (Astro/Next), or full-stack
4. Known boundaries (what to always do, ask first about, and never do)

Then generate a structured spec covering: objective, tech stack (from the house stack — Rust/Anchor/Solana, TypeScript, Astro 5 / Next 15 / Tailwind v4, Python), commands, project structure, code style (defer to the `fullstack-standard` skill), testing strategy (defer to `references/definition-of-done.md`), and boundaries.

Save the spec as `SPEC.md` in the project root and confirm with the user before proceeding.
