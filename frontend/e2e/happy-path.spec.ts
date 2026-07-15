import { test, expect } from "@playwright/test";
import { loginAs, mockApi, makeJob } from "./support";

test.describe("happy path", () => {
  test.beforeEach(async ({ context }) => {
    await loginAs(context);
  });

  test("dashboard lists a completed job, opens it, and downloads the result", async ({ page }) => {
    const job = makeJob({ id: "job-abc-123", status: "completed", cost_final: 5.0 });
    await mockApi(page, { jobs: [job], job });

    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Jobs", exact: true })).toBeVisible();
    // The list renders the real job with its status.
    await expect(page.getByText("ghcr.io/acme/trainer:latest").first()).toBeVisible();
    await expect(page.getByText("Completed").first()).toBeVisible();

    await page.getByRole("link", { name: "View" }).first().click();
    await expect(page).toHaveURL(/\/jobs\/job-abc-123/);
    await expect(page.getByText("Completed").first()).toBeVisible();

    // Download the result — the mocked endpoint streams bytes with a filename.
    const download = page.getByRole("button", { name: "Download result" });
    await expect(download).toBeVisible();
    const [dl] = await Promise.all([page.waitForEvent("download"), download.click()]);
    expect(await dl.suggestedFilename()).toContain("result");
  });

  test("submitting a job navigates to its detail page", async ({ page }) => {
    const queued = makeJob({ id: "job-new-999", status: "queued", cost_final: null });
    await mockApi(page, { submit: queued, job: queued });

    await page.goto("/jobs/new");
    await page.getByLabel("Image reference").fill("ghcr.io/acme/trainer:latest");

    const submit = page.getByRole("button", { name: "Submit job" });
    await expect(submit).toBeEnabled();
    await submit.click();

    await expect(page).toHaveURL(/\/jobs\/job-new-999/);
  });
});
