import { test, expect } from "@playwright/test";
import { loginAs, mockApi } from "./support";
import { mockWallet, TEST_ADDRESS, SIGNATURE } from "./wallet";

/**
 * Wallet is the only human sign-in.
 *
 * The API-key login is gone on purpose, so these tests assert its absence as much as
 * the wallet flow's presence: a key lives in scripts, CI and .env files, and if it also
 * opened the dashboard then one leaked key would carry billing and withdraw with it.
 *
 * The route handler talks to the backend server-side, where page.route cannot reach, so
 * /api/session is stubbed at the browser edge and the cookie it would set is seeded with
 * loginAs — same split the suite already used.
 */
const NONCE = "abc123nonce";
const SIWE_MESSAGE = `localhost:3100 wants you to sign in with your Ethereum account:\n${TEST_ADDRESS}\n\nNonce: ${NONCE}`;

/** Stub the challenge + verify pair; returns the body the page posted to /api/session. */
async function mockSiwe(page: import("@playwright/test").Page) {
  const posted: { body?: Record<string, unknown> } = {};

  await page.route("**/api/session/nonce*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ nonce: NONCE, message: SIWE_MESSAGE }),
    }),
  );
  await page.route("**/api/session", (route) => {
    posted.body = route.request().postDataJSON() as Record<string, unknown>;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, role: "developer" }),
    });
  });

  return posted;
}

test.describe("wallet sign-in", () => {
  test("connecting and signing lands on the dashboard, with no register step", async ({
    page,
    context,
  }) => {
    await mockWallet(page);
    await mockApi(page, { jobs: [] });
    const posted = await mockSiwe(page);
    await loginAs(context); // the cookie POST /api/session would have set

    await page.goto("/login");

    // Nothing to fill in: an address is the whole identity.
    await expect(page.getByLabel("API key")).toHaveCount(0);
    await expect(page.getByLabel("Account name")).toHaveCount(0);

    await page.getByRole("button", { name: "Connect wallet" }).click();
    await page.getByRole("button", { name: "Sign in with wallet" }).click();

    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByRole("heading", { name: "Jobs", exact: true })).toBeVisible();

    // The signature was exchanged for the session — not the address alone.
    expect(posted.body).toMatchObject({
      address: TEST_ADDRESS,
      nonce: NONCE,
      signature: SIGNATURE,
    });
  });

  test("a brand-new address needs no registration step", async ({ page, context }) => {
    // /auth/verify resolves-or-creates the developer, so a first-time wallet takes the
    // exact same path. The old /register route is gone and redirects here.
    await mockWallet(page);
    await mockApi(page, { jobs: [] });
    await mockSiwe(page);
    await loginAs(context);

    await page.goto("/register");
    await expect(page).toHaveURL(/\/login/);

    await page.getByRole("button", { name: "Connect wallet" }).click();
    await page.getByRole("button", { name: "Sign in with wallet" }).click();
    await expect(page).toHaveURL(/\/dashboard/);
  });

  test("declining the signature keeps the user on login", async ({ page }) => {
    await mockWallet(page, { rejectSign: true });
    await mockSiwe(page);

    await page.goto("/login");
    await page.getByRole("button", { name: "Connect wallet" }).click();
    await page.getByRole("button", { name: "Sign in with wallet" }).click();

    // By text, not by role: Next's own route announcer is also role="alert".
    await expect(page.getByText("You declined the signature.")).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test("an API key is not a way into the developer session", async ({ request }) => {
    // The route that used to accept { apiKey } now only speaks signatures. Asserted at
    // the route rather than the form, because the risk is a client posting it directly.
    const res = await request.post("/api/session", { data: { apiKey: "grdx_leaked_from_ci" } });
    expect(res.status()).toBe(422);
  });

  test("a protected route redirects to login when signed out", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login\?next=%2Fdashboard/);
  });
});

test.describe("provider sign-in", () => {
  test("the provider area sends signed-out operators to their own sign-in", async ({ page }) => {
    // Providers have no wallet identity backend-side, so the wallet page would be a dead end.
    await page.goto("/provider");
    await expect(page).toHaveURL(/\/provider-login\?next=%2Fprovider/);
  });

  test("a valid agent key opens the provider area", async ({ page, context }) => {
    await loginAs(context, "provider");
    await mockApi(page); // the provider area fetches on mount; keep it off the network
    await page.route("**/api/session/provider", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, role: "provider" }),
      }),
    );

    await page.goto("/provider-login");
    await page.getByLabel("Agent key").fill("grdx_provider_key");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page).toHaveURL(/\/provider/);
  });

  test("an invalid agent key shows an error and stays put", async ({ page }) => {
    await page.route("**/api/session/provider", (route) =>
      route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ message: "That agent key isn't valid." }),
      }),
    );

    await page.goto("/provider-login");
    await page.getByLabel("Agent key").fill("grdx_wrong");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page.getByText("That agent key isn't valid.")).toBeVisible();
    await expect(page).toHaveURL(/\/provider-login/);
  });
});
