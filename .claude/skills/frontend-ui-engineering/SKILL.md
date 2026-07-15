---
name: frontend-ui-engineering
description: Builds production-quality web UIs on eonedge's frontend stack — Astro 5, Next 15, Tailwind v4. Use when building or modifying user-facing interfaces. Use when creating components, implementing layouts, wiring interactivity, styling marketing or app pages, or when the output must look like a design-aware engineer built it rather than an AI. Frontend-only skill; pairs with browser-testing-with-devtools for runtime verification.
---

# Frontend UI Engineering

## Overview

Build web UI that is static-first, accessible, and visually deliberate — the kind a
design-aware engineer ships, not the kind an AI defaults to. On this stack that means
Astro/Next server rendering by default, the least client JS that does the job,
Tailwind v4 tokens instead of magic numbers, and interfaces that work in light and
dark from the first commit. This is a **frontend** skill: it governs everything that
ships to the browser. The full ruleset lives in `fullstack-standard` →
`references/frontend-standards.md`; this skill is how you apply it while building.

Ship the least JS, in the fewest layers, that looks like a human chose every pixel.

## When to Use

- Building new pages or components (Astro `.astro`, Next server/client components)
- Modifying existing user-facing interfaces or marketing pages
- Implementing responsive layouts and interaction patterns
- Adding just-enough interactivity or client state
- Fixing visual, UX, or accessibility issues

**When NOT to use:** anything off the browser — on-chain programs, servers, SDKs,
Python jobs. Those are backend work; see `backend-standards.md`. For designing the
typed contract the frontend consumes, use `api-and-interface-design`. To verify a
change in a real browser, use `browser-testing-with-devtools`.

## Rendering Strategy — decide before you write JSX

Least-JS-first. Pick the lightest tier that satisfies the requirement, and only
climb when interactivity forces it.

```
Static HTML (Astro page/component)        → marketing, docs, content — zero JS shipped
Server Component (Next, default)          → app pages that read data, no interactivity
Astro island / "use client" (Next)        → the ONE subtree that needs state/events
Client data-fetching (server state lib)   → live/remote data with caching, in a client leaf
```

Rules:
- **Astro is static-first.** Marketing and content sites render to HTML; add an island
  (`client:load`/`client:visible`) only for the specific widget that needs it.
- **Next is server-components-by-default.** `"use client"` is a deliberate choice for
  an interactive leaf, never the default at the top of the tree. Push it as deep as
  possible so the static shell stays static.
- If a page has no interactivity, it ships no component JS. Prove it — check the
  network panel (`browser-testing-with-devtools`).

## Component Architecture

Colocate what belongs to a component; keep each component doing one thing.

```
src/components/
  TaskList/
    TaskList.tsx / TaskList.astro   # implementation
    TaskList.test.tsx               # hermetic component test
    use-task-list.ts                # client hook, only if state is genuinely complex
    types.ts                        # component-local types (import shared API types, don't redefine)
```

**Compose, don't over-configure:**

```tsx
// Good: composable
<Card>
  <CardHeader><CardTitle>Nodes</CardTitle></CardHeader>
  <CardBody><NodeList nodes={nodes} /></CardBody>
</Card>

// Avoid: a prop for every decision
<Card title="Nodes" headerVariant="large" bodyPadding="md" content={<NodeList nodes={nodes} />} />
```

**Separate data from presentation.** Fetch on the server; render dumb.

```tsx
// Server component: fetches, handles the three non-happy states
export default async function NodeListPage() {
  const nodes = await getNodes();               // typed, imported from the server SDK
  if (nodes.length === 0) return <EmptyState message="No nodes registered yet" />;
  return <NodeList nodes={nodes} />;
}

// Presentation: pure, testable
export function NodeList({ nodes }: { nodes: Node[] }) {
  return (
    <ul role="list" className="divide-y divide-border">
      {nodes.map((n) => <NodeItem key={n.pubkey} node={n} />)}
    </ul>
  );
}
```

`Node` is imported from the backend's exported types — never re-declared client-side.
That is the type contract; see `api-and-interface-design`.

## State Management — simplest tier that works

```
Server render (no client state)      → default; most reads need no client state at all
Local state (useState / Astro store) → component-only UI state (open/closed, hover)
URL state (searchParams)             → filters, pagination, tabs — shareable & SSR-friendly
Context                              → theme, wallet/session (read-heavy, write-rare)
Server-state lib (TanStack Query)    → live remote data in a client leaf, with caching
Global store (Zustand)              → only when app-wide client state truly demands it
```

Prefer URL state over client state for anything a user might link to or reload into.
Avoid prop drilling past ~3 levels — restructure or lift to context.

## Design System Adherence — no AI aesthetic

AI-generated UI is recognizable. Kill every tell. Use the project's actual tokens.

| AI Default | Why It's a Problem | Do This Instead |
|---|---|---|
| Purple/indigo everything | The "safe" model palette — makes every app look identical | Use the project's real palette / Tailwind theme tokens |
| Gradient soup | Visual noise that clashes with the design system | Flat, or one subtle gradient the system defines |
| `rounded-2xl` on everything | Max rounding ignores the real radius hierarchy | One consistent radius scale from the theme |
| Generic hero + three feature cards | Template with no tie to the actual content | Content-first layout built around the real message |
| Lorem ipsum | Hides wrapping/overflow bugs real copy reveals | Realistic copy at realistic lengths |
| Oversized padding everywhere | Equal generous padding destroys hierarchy | The spacing scale, applied by importance |
| Uniform stock card grids | Ignores information priority | Purpose-driven layout, emphasis where it matters |
| Shadow-heavy depth | Competes with content, janky on low-end devices | Subtle/no shadow unless the system specifies |

**Spacing** — stay on the Tailwind scale. `p-4`, `gap-3` — never arbitrary `p-[13px]`
or `mt-[2.3rem]`.

**Typography** — respect the hierarchy: one `h1` per page, `h2`→section, `h3`→
subsection. Don't skip levels; don't use heading styles for non-headings.

**Color** — semantic tokens (`text-foreground`, `bg-surface`, `border-border`), not
raw hex. Never use color as the *only* signal — pair with icon/text. Contrast ≥ 4.5:1
normal, 3:1 large, **in both themes**.

## Light + Dark — non-negotiable

Both themes are a shipping requirement, not a follow-up.

- Design against tokens that flip with the theme; never hardcode `#fff`/`#000`.
- Verify contrast in **both** modes — a passing light contrast can fail in dark.
- Reserve image/embed space so neither theme shifts layout.

## Accessibility (WCAG 2.1 AA — the floor)

Semantic HTML first; ARIA only to fill a real gap.

```tsx
<button onClick={onClick}>Save</button>        // ✓ focusable, keyboard, role for free
<div onClick={onClick}>Save</div>              // ✗ invisible to keyboard & AT

<button aria-label="Close dialog"><XIcon /></button>   // icon-only needs a name
<label htmlFor="rpc">RPC endpoint</label><input id="rpc" />
```

- **Keyboard:** every interactive element is Tab-reachable with a visible focus ring;
  logical order; no traps. Move focus into dialogs and back on close.
- **Meaningful empty/error/loading states** — never a blank screen. Skeletons for
  content loads (not spinners); `role="status"` on empty/loading regions.
- Respect `prefers-reduced-motion`; any motion must be disableable.
- No cumulative layout shift — reserve space for async content.

## Responsive Design

Mobile-first, expand up. Verify at 320 / 768 / 1024 / 1440.

```tsx
<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
```

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll add `"use client"` at the top, it's easier" | That drags the whole tree client-side and ships JS you don't need. Push the boundary to the interactive leaf. |
| "Dark mode later" | Retrofitting themes means re-auditing every color. Build against tokens now. |
| "Accessibility is a nice-to-have" | It's a legal and quality requirement. Semantic HTML costs nothing up front. |
| "We'll make it responsive later" | Retrofitting responsive is ~3x the work. Mobile-first from the start. |
| "The design isn't final, so I'll skip styling" | Use the design-system defaults. Unstyled UI reads as broken to reviewers. |
| "It's just a prototype" | Prototypes become production. Build the foundation right. |
| "The AI look is fine for now" | It signals low quality. Use the real palette and tokens from line one. |
| "I'll redefine the API type here, it's quicker" | That forks the contract. Import the backend's exported type — one source of truth. |

## Red Flags

- `"use client"` at the top of a page/route that mostly renders static content
- Components over ~200 lines (split them)
- Arbitrary Tailwind values (`p-[13px]`, `text-[#6b21a8]`) instead of scale/tokens
- Hardcoded colors that don't flip for dark mode
- Missing empty / error / loading states
- No keyboard pass; color as the sole state indicator
- Generic AI look (purple gradients, oversized cards, stock hero)
- API request/response shapes re-declared on the client instead of imported

## Verification

Run the frontend Definition-of-Done gate (`fullstack-standard` →
`references/definition-of-done.md`). Beyond the commands, confirm:

- [ ] Least-JS tier chosen — static/server where no interactivity is needed; no
      `"use client"` above the interactive leaf (checked in the network panel)
- [ ] `pnpm lint`, `pnpm tsc --noEmit`, `pnpm prettier -c .`, `pnpm build` all clean
- [ ] No console errors/warnings on load (verify via `browser-testing-with-devtools`)
- [ ] Keyboard-navigable end-to-end; visible focus; no traps
- [ ] Works in **light and dark**; contrast passes in both
- [ ] Responsive at 320 / 768 / 1024 / 1440; no layout shift
- [ ] Loading, error, and empty states all handled
- [ ] Uses theme tokens (spacing, color, radius, type) — no arbitrary values
- [ ] Shared API types imported, not redefined; no secrets in client code

## See Also

- `fullstack-standard` — core philosophy + the Definition-of-Done gate; frontend rules in `references/frontend-standards.md`
- `browser-testing-with-devtools` — verify the UI in a real browser (console, network, a11y tree, screenshots)
- `api-and-interface-design` — the typed contract the frontend imports and consumes
