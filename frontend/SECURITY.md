# Frontend security posture (Session 14.5)

## Credential handling

- The developer/provider **API key never reaches browser JavaScript.** It's stored
  in an httpOnly cookie (`gridix_session`); the browser talks only to same-origin
  Next route handlers (`/api/*`), which attach `Authorization: Bearer` server-side.
- **No private keys** are in the app. Signing happens in the user's own wallet
  (injected provider); the app only ever holds public data — contract addresses,
  the RPC URL, the chain id (all `NEXT_PUBLIC_*`).
- Verified: a scan of the production client bundle finds no API keys and no
  private keys — only public crypto constants (secp256k1 order/prime, EVM
  bytecode) from viem, and the `grdx_your_key` documentation placeholder.

## HTTP security headers

Set in `src/middleware.ts` (not `next.config` `headers()`, which drops CSP/HSTS
on full-route-cache hits) so they apply to static, dynamic, and cached responses:

| Header                      | Value / intent                                 |
| --------------------------- | ---------------------------------------------- |
| `Content-Security-Policy`   | see below                                      |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` |
| `X-Frame-Options`           | `DENY` (also `frame-ancestors 'none'` in CSP)  |
| `X-Content-Type-Options`    | `nosniff`                                      |
| `Referrer-Policy`           | `strict-origin-when-cross-origin`              |
| `Permissions-Policy`        | `camera=(), microphone=(), geolocation=()`     |

### CSP

The app is self-contained — no third-party scripts, all backend traffic proxied
same-origin — so the policy is tight. The only cross-origin connection is the
wallet's chain RPC, scoped in `connect-src`.

- `script-src 'self' 'nonce-<per-request>' 'strict-dynamic'` — **no `'unsafe-inline'`
  for scripts** (pentest C2/H13). Middleware mints a fresh nonce per request and Next
  stamps it onto its inline hydration scripts; `strict-dynamic` lets those trusted
  scripts load the app's chunks. An injected inline `<script>` from an XSS has no valid
  nonce, so it cannot execute. This requires per-request rendering, so the root layout
  sets `export const dynamic = "force-dynamic"` — a deliberate trade of static caching
  for real XSS protection on a money-handling app.
- `style-src 'self' 'unsafe-inline'` — inline styles are still allowed (Tailwind /
  next-font inject `<style>`); style injection can't exfiltrate a session the way script
  execution can, and the session cookie is httpOnly regardless.
- `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, `frame-ancestors 'none'`
  close common injection/clickjacking vectors.
- Verified on real responses (not just the config) by an E2E gate that also asserts the
  nonce is actually stamped onto every script tag.

## Dependency audit

Run `pnpm audit` (or Dependabot) against the pinned lockfile. Note: pnpm's classic
audit endpoint has been retired by the npm registry (HTTP 410); use a pnpm version
that targets the bulk advisory endpoint, or GitHub Dependabot, in CI.
