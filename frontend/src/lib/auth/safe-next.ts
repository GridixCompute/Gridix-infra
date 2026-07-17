/**
 * Sanitise a `next` redirect target down to a same-origin path.
 *
 * `next` is attacker-controllable — `/login?next=https://evil.com/phish` — and it is
 * consumed at the single most convincing moment for a phishing hand-off: immediately after
 * the user submits valid credentials. Left unvalidated, `router.replace(next)` performs a
 * full off-site navigation (pentest H14).
 *
 * Anything that is not a plain site-relative path is discarded and the caller falls back to
 * its own default. The explicit `//` and `/\` rejections matter: both are absolute
 * protocol-relative forms in browsers despite starting with a slash, so a naive
 * `startsWith("/")` check alone still lets `//evil.com` through.
 */
export function safeNext(raw: string | null | undefined, origin: string): string | null {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) {
    return null;
  }
  try {
    const url = new URL(raw, origin);
    // Belt and braces: whatever the string looked like, only keep it if it actually
    // resolved to this origin, and hand back only the path we control.
    if (url.origin !== origin) return null;
    return url.pathname + url.search + url.hash;
  } catch {
    return null;
  }
}
