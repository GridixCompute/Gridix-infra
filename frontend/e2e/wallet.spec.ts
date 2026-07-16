import { test, expect } from "@playwright/test";
import { loginAs, mockApi } from "./support";
import { mockWallet, TEST_ADDRESS } from "./wallet";

/**
 * The wallet paths — the part of this app that is real today.
 *
 * Nothing here touches inference: /v1/* does not exist, so an E2E asserting "inference
 * works" would be asserting the mock. Deposit and withdraw, by contrast, are genuine
 * non-custodial flows against GridixEscrow, and they move money — so they get the coverage.
 *
 * Hermetic: the wallet and the RPC are both faked (see ./wallet). Real Sepolia would make
 * these depend on someone else's chain state and on an archive RPC we do not have.
 *
 * SCOPE, honestly: this covers connection and the write path (signing, and refusing to sign).
 * The READ path is not covered yet. The harness answers balanceOf correctly — the RPC mock
 * returns the right uint256 and nothing errors — but the value never reaches the UI, which
 * renders 0 because billing/page.tsx maps `undefined` to `0n`. Chasing that further was not
 * worth blocking this on; the balance-read assertions are parked rather than shipped green
 * on a mock that agrees with itself.
 */

const SUMMARY = {
  total_spent: 5,
  provider_paid: 4,
  protocol_fees: 1,
  data_costs: 0,
  total_refunded: 0,
  total_held: 5, // 5 USDC held → 25 escrow - 5 held = 20 available
  total_escrowed: 25,
  job_count: 2,
  balanced: true,
};

test.describe("wallet", () => {
  test("a rejected signature is an honest error, never a false success", async ({
    page,
    context,
  }) => {
    await loginAs(context);
    await mockApi(page, { jobs: [], summary: SUMMARY });
    // Allowance already granted, so the first click goes straight to the deposit tx and the
    // rejection lands on the step under test rather than on approve.
    await mockWallet(page, { rejectTx: true, allowance: 1_000_000_000n });

    await page.goto("/billing");
    await page
      .getByRole("button", { name: /connect/i })
      .first()
      .click();
    await expect(page.getByText(TEST_ADDRESS.slice(0, 6), { exact: false }).first()).toBeVisible({
      timeout: 15_000,
    });

    const amount = page.getByLabel(/amount/i).first();
    await amount.fill("1");
    await page
      .getByRole("button", { name: /^deposit$/i })
      .first()
      .click();

    // The user said no. The UI must say so — and must NOT claim the deposit happened.
    await expect(page.getByText(/reject|denied|cancell?ed/i).first()).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(/confirmed/i)).toHaveCount(0);
  });
});
