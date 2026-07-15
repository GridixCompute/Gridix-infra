import { test, expect } from "@playwright/test";

/**
 * Security headers gate (Sesi 14.5): every response carries the hardening
 * headers, so a regression that drops them fails the PR.
 */
test("responses carry the security headers", async ({ page }) => {
  const res = await page.goto("/login");
  const headers = res!.headers();

  const csp = headers["content-security-policy"] ?? "";
  expect(csp).toContain("default-src 'self'");
  expect(csp).toContain("object-src 'none'");
  expect(csp).toContain("frame-ancestors 'none'");

  expect(headers["strict-transport-security"]).toContain("max-age=");
  expect(headers["x-frame-options"]).toBe("DENY");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
});
