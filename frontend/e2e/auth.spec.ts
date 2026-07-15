import { test, expect } from "@playwright/test";
import { loginAs, mockApi } from "./support";

test.describe("auth", () => {
  test("registration reveals the API key exactly once and gates on saving it", async ({ page }) => {
    await page.route("**/api/developers", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ id: "dev-1", name: "Acme AI", apiKey: "grdx_shown_once_123" }),
      }),
    );

    await page.goto("/register");
    await page.getByLabel("Account name").fill("Acme AI");
    await page.getByRole("button", { name: "Create account" }).click();

    await expect(page.getByRole("heading", { name: "Save your API key" })).toBeVisible();
    await expect(page.getByText("grdx_shown_once_123")).toBeVisible();

    // The continue button is gated until the user confirms they saved the key.
    const cont = page.getByRole("button", { name: "Continue to dashboard" });
    await expect(cont).toBeDisabled();
    await page.getByRole("checkbox").check();
    await expect(cont).toBeEnabled();
  });

  test("a protected route redirects to login when signed out", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login\?next=%2Fdashboard/);
  });

  test("an invalid API key shows an error and stays on login", async ({ page }) => {
    await page.route("**/api/session", (route) =>
      route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ message: "That API key isn't valid." }),
      }),
    );

    await page.goto("/login");
    await page.getByLabel("API key").fill("grdx_wrong");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page.getByText("That API key isn't valid.")).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test("a valid login lands on the dashboard", async ({ page, context }) => {
    // The real login route sets the session cookie; simulate that, then mock the
    // validation response so the client routes by role.
    await loginAs(context);
    await mockApi(page, { jobs: [] });
    await page.route("**/api/session", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, role: "developer" }),
      }),
    );

    await page.goto("/login");
    await page.getByLabel("API key").fill("grdx_e2e_key");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByRole("heading", { name: "Jobs", exact: true })).toBeVisible();
  });
});
