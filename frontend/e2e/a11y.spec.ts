import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { loginAs, mockApi, makeJob } from "./support";

/**
 * Accessibility gate (Sesi 13.2): the main pages must pass an axe audit against
 * WCAG 2.1 A/AA. A regression here fails CI. Usable without a mouse is covered
 * separately by the keyboard test below.
 */
async function scan(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  return results.violations;
}

test.describe("accessibility", () => {
  // Split per page for the same reason as the authenticated set below: five pages plus five
  // axe scans in one test sits right on the 30s budget, so it passed alone and failed under
  // the full suite. A gate that fails on load rather than on merit teaches people to re-run
  // it instead of read it.
  for (const path of ["/", "/docs", "/login", "/provider-login", "/provider-register"]) {
    test(`${path} has no axe violations`, async ({ page }) => {
      await page.goto(path);
      const violations = await scan(page);
      expect(violations, `${path}: ${violations.map((v) => v.id).join(", ")}`).toEqual([]);
    });
  }

  /**
   * One test per page, rather than one test walking them all.
   *
   * The `marker` is a landmark that exists only once the page has really rendered: without
   * it, a page still showing its skeleton audits clean and the gate passes on nothing — the
   * failure mode that makes an a11y gate worse than none, because it reports safety it never
   * checked. But waiting for real content costs time, and five pages in one test blew the
   * 30s budget. Split, so each page gets its own budget, they run in parallel, and a failure
   * names the page instead of the loop.
   */
  const AUTHED_PAGES: [path: string, marker: string][] = [
    ["/dashboard", "h1"],
    ["/jobs/new", "form"],
    ["/billing", "h1"],
    ["/playground", 'textarea[aria-label="Prompt"]'],
    ["/models", "table"],
  ];

  for (const [path, marker] of AUTHED_PAGES) {
    test(`${path} has no axe violations`, async ({ page, context }) => {
      await loginAs(context);
      await mockApi(page, { jobs: [makeJob({ status: "completed" })] });

      await page.goto(path);
      await page.waitForSelector(marker, { timeout: 15_000 });
      const violations = await scan(page);
      expect(violations, `${path}: ${violations.map((v) => v.id).join(", ")}`).toEqual([]);
    });
  }

  test("the app is navigable from the keyboard", async ({ page, context }) => {
    await loginAs(context);
    await mockApi(page, { jobs: [] });
    await page.goto("/dashboard");

    // Tab reaches an interactive element and it shows a visible focus outline.
    await page.keyboard.press("Tab");
    const focused = page.locator(":focus-visible");
    await expect(focused).toBeVisible();
  });
});
