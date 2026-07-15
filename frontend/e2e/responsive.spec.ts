import { test, expect } from "@playwright/test";
import { loginAs, mockApi, makeJob } from "./support";

/**
 * Mobile usability (Sesi 13.3): people check job status from a phone, so no main
 * page may overflow horizontally at 375px. Wide content (tables) must scroll
 * inside its own container, never the page body.
 */
test.use({ viewport: { width: 375, height: 800 } });

async function expectNoOverflow(page: import("@playwright/test").Page, path: string) {
  await page.goto(path, { waitUntil: "domcontentloaded" });
  // Poll so late layout shifts (fonts/images) settle before we judge.
  await expect
    .poll(
      () =>
        page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        ),
      { message: `${path} overflows horizontally at 375px`, timeout: 5000 },
    )
    .toBeLessThanOrEqual(1);
}

test.describe("responsive @ 375px", () => {
  test("public pages don't overflow horizontally", async ({ page }) => {
    for (const path of ["/", "/login", "/register", "/provider-register"]) {
      await expectNoOverflow(page, path);
    }
  });

  test("authenticated pages don't overflow horizontally", async ({ page, context }) => {
    await loginAs(context);
    await mockApi(page, {
      jobs: [makeJob({ status: "completed" }), makeJob({ id: "job-2", status: "running" })],
      summary: {
        total_spent: 12.34,
        provider_paid: 10,
        protocol_fees: 1.34,
        data_costs: 1,
        total_refunded: 3,
        total_held: 2,
        total_escrowed: 20,
        job_count: 5,
        balanced: true,
      },
    });

    for (const path of ["/dashboard", "/jobs", "/jobs/new", "/billing", "/settings"]) {
      await expectNoOverflow(page, path);
    }
  });
});
