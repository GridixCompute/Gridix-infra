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
  test("public pages have no axe violations", async ({ page }) => {
    for (const path of ["/", "/login", "/register", "/provider-register"]) {
      await page.goto(path);
      const violations = await scan(page);
      expect(violations, `${path}: ${violations.map((v) => v.id).join(", ")}`).toEqual([]);
    }
  });

  test("authenticated developer pages have no axe violations", async ({ page, context }) => {
    await loginAs(context);
    await mockApi(page, { jobs: [makeJob({ status: "completed" })] });

    for (const path of ["/dashboard", "/jobs/new", "/billing"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const violations = await scan(page);
      expect(violations, `${path}: ${violations.map((v) => v.id).join(", ")}`).toEqual([]);
    }
  });

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
