import { test, expect } from "@playwright/test";
import { mockWallet } from "./wallet";

/**
 * The playground is public. These drive it as a stranger would: no cookies, no account.
 *
 * The two halves are gated differently, so both are checked. A build that redirected
 * /playground to /login would fail the first test; a build that hid the image tab from
 * signed-out visitors, or errored at them, would fail the second.
 */

const CHUNK = (text: string) =>
  `data: ${JSON.stringify({
    object: "chat.completion.chunk",
    choices: [{ index: 0, delta: { content: text }, finish_reason: null }],
  })}\n\n`;

/** Stub the free tier so the page never touches a real coordinator. */
async function mockFreeTier(
  page: import("@playwright/test").Page,
  opts: { quota?: object | null } = {},
) {
  await page.route("**/api/public/chat", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: CHUNK("Hello from the free tier.") + "data: [DONE]\n\n",
    }),
  );
  await page.route("**/api/public/models", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ chat: [{ id: "llama3.2-3b", free: true }], images: [] }),
    }),
  );
  await page.route("**/api/public/images/quota", (route) =>
    opts.quota
      ? route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(opts.quota),
        })
      : // 401 is the ordinary signed-out state, not a failure.
        route.fulfill({ status: 401, contentType: "application/json", body: "{}" }),
  );
}

test.describe("the playground is open to anyone", () => {
  test("a signed-out visitor reaches it without being redirected to login", async ({ page }) => {
    await mockFreeTier(page);
    await page.goto("/playground");
    await expect(page).toHaveURL(/\/playground$/);
    await expect(page.getByRole("heading", { name: "Playground" })).toBeVisible();
  });

  test("they can chat with no account at all", async ({ page }) => {
    await mockFreeTier(page);
    await page.goto("/playground");

    await page.getByLabel("Prompt").fill("hi there");
    await page.getByRole("button", { name: "Send" }).click();

    await expect(
      page.getByRole("log", { name: "Conversation" }).getByText(/Hello from the free tier/),
    ).toBeVisible();
  });

  test("the image tab invites a wallet instead of erroring or hiding", async ({ page }) => {
    await mockFreeTier(page);
    await page.goto("/playground");
    await page.getByRole("tab", { name: "image" }).click();

    await expect(page.getByText(/connect a wallet to generate images/i)).toBeVisible();
    await expect(page.getByText(/5 per day/i)).toBeVisible();
    // Not an error: nothing is broken, the visitor simply has not connected yet.
    // Scoped to <main>, because Next renders a route announcer with role="alert" on every
    // page — an unscoped query matches that and never means what it looks like it means.
    await expect(page.locator("main").getByRole("alert")).toHaveCount(0);
  });

  test("once a wallet is connected the allowance is shown", async ({ page }) => {
    await mockWallet(page);
    await mockFreeTier(page, {
      quota: { limit: 5, used: 1, remaining: 4, resets: "00:00 UTC", available: true },
    });
    await page.goto("/playground");
    await page.getByRole("tab", { name: "image" }).click();

    await page
      .getByRole("button", { name: /connect/i })
      .first()
      .click();

    // The number is on screen, so nobody has to discover the limit by hitting it.
    await expect(page.getByTestId("image-quota")).toContainText("4 of 5");
  });
});
