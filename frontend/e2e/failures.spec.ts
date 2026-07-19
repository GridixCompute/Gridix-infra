import { test, expect } from "@playwright/test";
import { loginAs, mockApi } from "./support";

/**
 * The failure paths matter most (Session 12.4): each must show a correct message,
 * never a broken screen.
 */
test.describe("failure paths", () => {
  test.beforeEach(async ({ context }) => {
    await loginAs(context);
  });

  test("insufficient balance blocks submit and prompts to deposit", async ({ page }) => {
    await mockApi(page, {
      submit: {
        status: 403,
        detail: "Insufficient balance: job needs 5 USDC escrow but only 0 USDC is available.",
      },
    });

    await page.goto("/jobs/new");
    await page.getByLabel("Image reference").fill("ghcr.io/acme/trainer:latest");
    await page.getByRole("button", { name: "Submit job" }).click();

    await expect(page.getByText(/Insufficient balance/)).toBeVisible();
    const deposit = page.getByRole("link", { name: "Deposit USDC" });
    await expect(deposit).toHaveAttribute("href", "/billing");
    await expect(page).toHaveURL(/\/jobs\/new/); // not navigated away
  });

  test("a backend error shows an error state with retry, not a blank screen", async ({ page }) => {
    await mockApi(page, { jobsError: { status: 500, detail: "boom" } });

    await page.goto("/dashboard");
    // The list degrades to an error state with a retry, never a blank screen.
    await expect(page.getByRole("heading", { name: "Something went wrong" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  test("a full backend outage shows an honest connectivity banner", async ({ page }) => {
    await mockApi(page, { jobsError: { status: 500, detail: "down" } });

    await page.goto("/dashboard");
    await expect(page.getByText(/Can't reach GRIDIX right now/)).toBeVisible();
  });

  test("an expired session redirects to login", async ({ page }) => {
    await mockApi(page, { jobsError: { status: 401, detail: "Not signed in." } });

    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);
  });

  test("the submit button stays disabled until the form is valid", async ({ page }) => {
    await mockApi(page);
    await page.goto("/jobs/new");

    const submit = page.getByRole("button", { name: "Submit job" });
    await expect(submit).toBeDisabled(); // image ref is required
    await page.getByLabel("Image reference").fill("ghcr.io/acme/trainer:latest");
    await expect(submit).toBeEnabled();
  });
});
