# Frontend standards

Rules for everything that ships to the browser: web pages, UI, and the client-side
TypeScript that drives them. The Core Philosophy in `SKILL.md` (minimal abstraction,
type-driven, ship-fast-not-sloppy, repo is truth) governs all of it — this file is
the concrete application on the client. Backend rules live separately in
`backend-standards.md`.

---

## Web — Astro 5 / Next 15 / Tailwind v4

- **Static-first.** Marketing sites are static (Astro) where possible; ship the
  least JS that does the job. Next.js: server components by default, `"use client"`
  only when you need interactivity/state.
- **One job per page.** A page informs, convinces, or redirects — give it a single
  clear CTA. No dead links, no filler.
- **Quality bar:** responsive, accessible (semantic HTML, alt text, focus states,
  contrast), works in **light and dark**, no layout shift, images optimized.
- Tailwind v4 conventions; keep class soup readable — extract components, not
  utility spaghetti. No inline styles when a utility exists.

---

## Browser TypeScript

- `tsconfig` with `"strict": true`. No `any`. No non-null `!` to silence the
  checker — narrow the type properly.
- **Consume, don't redefine.** Import the shared types the backend exports; never
  re-declare API request/response shapes on the client. One source of truth.
- Keep data-fetching typed end-to-end; validate anything crossing the network
  boundary you don't control.
- `pnpm lint` clean; format with prettier. Component/interaction tests hermetic.

---

## Accessibility & UX (non-negotiable)

- Semantic HTML first; ARIA only to fill real gaps, never as a substitute.
- Keyboard-navigable: visible focus states, logical tab order, no traps.
- Sufficient color contrast in **both** light and dark themes.
- Respect `prefers-reduced-motion`; don't ship motion that can't be turned off.
- No cumulative layout shift — reserve space for images/embeds.

---

## Cross-cutting (all frontend code)

- **Comments explain *why*, not *what*.** A comment earns its place by explaining a
  non-obvious decision or invariant.
- **Match the surrounding code** — naming, structure, and idiom of the file you're
  editing win over personal preference.
- **No secrets in client code** — anything shipped to the browser is public. Public
  keys/endpoints only; everything sensitive stays server-side.
- **Delete dead code.** No commented-out blocks left "just in case" — git remembers.
