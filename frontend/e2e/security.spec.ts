import { test, expect } from "@playwright/test";

/**
 * Security headers gate (Session 14.5 / pentest C2+H13): every response carries the
 * hardening headers, and the CSP is strict — script-src is nonce-based with NO
 * 'unsafe-inline', so an injected inline script can't execute. Verified on a real
 * response (not the config), the lesson from the header cache-hit bug.
 */
test("responses carry a strict, nonce-based CSP and the hardening headers", async ({ page }) => {
  const res = await page.goto("/login");
  const headers = res!.headers();

  const csp = headers["content-security-policy"] ?? "";
  expect(csp).toContain("default-src 'self'");
  expect(csp).toContain("object-src 'none'");
  expect(csp).toContain("frame-ancestors 'none'");
  expect(csp).toContain("base-uri 'self'");
  expect(csp).toContain("form-action 'self'");

  // script-src must be nonce-based and must NOT allow inline scripts.
  const scriptSrc = /script-src ([^;]*)/.exec(csp)?.[1] ?? "";
  expect(scriptSrc).toMatch(/'nonce-[A-Za-z0-9+/=]+'/);
  expect(scriptSrc).not.toContain("'unsafe-inline'");

  expect(headers["strict-transport-security"]).toContain("max-age=");
  expect(headers["x-frame-options"]).toBe("DENY");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
});

test("the headers survive a cache hit — the bug this gate exists for", async ({ page }) => {
  // The original bug: headers set in next.config's headers() are dropped on a full-route
  // cache hit, so the FIRST request looked perfectly secure and later ones shipped naked.
  // The test above makes one request and would not have caught it. This makes a second.
  const first = await page.goto("/login");
  const second = await page.goto("/login");

  for (const res of [first!, second!]) {
    const h = res.headers();
    expect(h["content-security-policy"] ?? "").toContain("default-src 'self'");
    expect(h["strict-transport-security"]).toContain("max-age=");
    expect(h["x-frame-options"]).toBe("DENY");
  }

  // Stronger than "present twice": a per-request nonce that repeats would mean the response
  // (headers and all) came from a cache, which is exactly how the headers went missing.
  const nonceOf = (res: NonNullable<typeof first>) =>
    /'nonce-([A-Za-z0-9+/=]+)'/.exec(res.headers()["content-security-policy"] ?? "")?.[1];
  const a = nonceOf(first!);
  const b = nonceOf(second!);
  expect(a).toBeTruthy();
  expect(b).toBeTruthy();
  expect(a, "the CSP nonce repeated across requests — the response is being cached").not.toEqual(b);
});

test("the CSP nonce is applied to Next's inline scripts (app hydrates)", async ({ page }) => {
  // If the nonce weren't stamped onto the scripts, the strict CSP would block them and
  // the app wouldn't hydrate. Assert every script tag carries a nonce.
  const res = await page.goto("/login");
  const html = (await res!.text()) ?? "";
  const scripts = html.match(/<script\b/g)?.length ?? 0;
  const nonced = html.match(/<script\b[^>]*\snonce="/g)?.length ?? 0;
  expect(scripts).toBeGreaterThan(0);
  expect(nonced).toBe(scripts);
});
