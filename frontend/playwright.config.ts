import { defineConfig, devices } from "@playwright/test";

/**
 * E2E config (Session 12). The suite is hermetic: every backend call is mocked at
 * the network boundary (see e2e/support), so it needs no live backend or chain
 * and runs deterministically in CI on Node alone. It exercises the real app —
 * routing, middleware, forms, error handling — against controlled responses.
 *
 * Requires a production build first (`pnpm build`); the webServer runs it.
 */
const PORT = 3100;
const isCI = !!process.env.CI;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  workers: isCI ? 2 : undefined,
  reporter: isCI ? [["list"], ["github"]] : [["list"]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `pnpm start -p ${PORT}`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !isCI,
    timeout: 120_000,
  },
});
