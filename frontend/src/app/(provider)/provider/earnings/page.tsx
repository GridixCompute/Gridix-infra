"use client";

import { Card, CardBody, CardTitle } from "@/components/ui/Card";
import { ConnectWallet } from "@/components/chain/ConnectWallet";
import { NetworkGuard } from "@/components/chain/NetworkGuard";
import { StakePanel } from "@/components/provider/StakePanel";
import { EarningsPanel } from "@/components/provider/EarningsPanel";

/**
 * Provider economics (Sesi 11.4 / 11.5). Stake, earnings and withdraw all live
 * on-chain in GridixStaking — the same wallet-driven pattern as developer
 * deposits. The provider's connected wallet is the staker and settlement payee.
 */
export default function EarningsPage() {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
            Stake & earnings
          </h1>
          <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
            Stake USDC to receive jobs; withdraw what you earn. All on-chain on Sepolia.
          </p>
        </div>
        <ConnectWallet />
      </div>

      <NetworkGuard>
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardBody className="space-y-4">
              <CardTitle className="!mt-0">Collateral</CardTitle>
              <StakePanel />
            </CardBody>
          </Card>
          <Card>
            <CardBody className="space-y-4">
              <CardTitle className="!mt-0">Earnings</CardTitle>
              <EarningsPanel />
            </CardBody>
          </Card>
        </div>
      </NetworkGuard>
    </div>
  );
}
