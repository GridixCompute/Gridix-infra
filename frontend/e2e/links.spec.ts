import { test, expect } from "@playwright/test";

/**
 * Link integrity: an internal link must reach something.
 *
 * This gate exists because the landing page shipped a hero CTA pointing at /docs/quickstart,
 * a route that never existed — quickstart is a section inside /docs, not a page. One of the
 * two primary conversion CTAs 404'd, and every other gate was green: the a11y suite loads /
 * and /docs but never follows a link between them, and a 404 renders perfectly accessible.
 *
 * Fragments are checked too, not just paths. /docs#quickstart is only correct for as long as
 * something on /docs still carries that id; the day the section is renamed, the link starts
 * scrolling nowhere and no other test would notice.
 */

const PAGES = ["/", "/docs", "/login"];

/** Internal, non-empty, non-hash-only targets — a bare "#" is a real pattern, not a broken link. */
async function internalLinks(page: import("@playwright/test").Page): Promise<string[]> {
  const hrefs = await page
    .locator("a[href^='/']")
    .evaluateAll((links) => links.map((a) => a.getAttribute("href") ?? ""));
  return [...new Set(hrefs.filter(Boolean))];
}

test.describe("link integrity", () => {
  test("the header Playground link lands on the playground itself", async ({ page }) => {
    // This used to assert a redirect to /login, because /playground was private and the link
    // was a sign-in funnel. It is public now — the free tier is the point of it — so landing
    // anywhere but the playground would mean turning away exactly the visitor it exists for.
    // Still worth pinning: the generic gate below only rejects 404s, so a redirect to some
    // other page would pass it while being just as wrong.
    await page.goto("/");
    await page.getByRole("navigation", { name: "Primary" }).getByText("Playground").click();

    await expect(page).toHaveURL(/\/playground$/);
    await expect(page.getByRole("heading", { name: "Playground" })).toBeVisible();
  });

  for (const path of PAGES) {
    test(`${path} links only to pages that exist`, async ({ page }) => {
      await page.goto(path);
      const links = await internalLinks(page);
      // A page with no internal links means the selector broke, not that the page is clean.
      expect(links.length, `${path} yielded no internal links to check`).toBeGreaterThan(0);

      for (const href of links) {
        const [pathname, hash] = href.split("#");
        const response = await page.goto(pathname || path);
        expect(response?.status(), `${path} → ${href} is a dead route`).not.toBe(404);

        if (hash) {
          await expect(
            page.locator(`#${hash}`),
            `${path} → ${href} lands on a fragment that is not on the page`,
          ).toHaveCount(1);
        }
      }
    });
  }
});
