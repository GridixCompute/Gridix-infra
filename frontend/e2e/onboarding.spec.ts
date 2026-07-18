import { test, expect } from "@playwright/test";
import { loginAs, mockApi, makeJob } from "./support";

/**
 * First-run onboarding (Session 14.2): a new developer is guided to their first
 * job without asking — a getting-started checklist and a one-click sample.
 */
test.describe("onboarding", () => {
  test.beforeEach(async ({ context }) => {
    await loginAs(context);
  });

  test("a new developer sees the getting-started guide on the empty dashboard", async ({
    page,
  }) => {
    await mockApi(page, { jobs: [] });
    await page.goto("/dashboard");

    await expect(page.getByText("Get started in two steps")).toBeVisible();
    await expect(page.getByRole("link", { name: "Fund escrow" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Try a sample job" })).toBeVisible();
  });

  test("the sample link prefills a runnable job on the submit form", async ({ page }) => {
    await mockApi(page);
    await page.goto("/jobs/new?sample=1");

    await expect(page.getByLabel("Image reference")).toHaveValue("docker.io/library/hello-world");
    await expect(page.getByRole("button", { name: "Submit job" })).toBeEnabled();
  });

  test("the guide is hidden once the developer has jobs", async ({ page }) => {
    await mockApi(page, { jobs: [makeJob()] });
    await page.goto("/dashboard");

    await expect(page.getByRole("heading", { name: "Jobs", exact: true })).toBeVisible();
    await expect(page.getByText("Get started in two steps")).toHaveCount(0);
  });
});
