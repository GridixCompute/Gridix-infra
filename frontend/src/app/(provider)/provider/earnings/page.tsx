"use client";

import dynamic from "next/dynamic";
import { Card, CardBody, CardTitle } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { ConnectWallet } from "@/components/chain/ConnectWallet";
import { NetworkGuard } from "@/components/chain/NetworkGuard";

// Lazy-load the on-chain staking/earnings write paths (wagmi/actions) so the
// wallet code ships only when this page's panels mount (Sesi 13.4).
const StakePanel = dynamic(
  () => import("@/components/provider/StakePanel").then((m) => m.StakePanel),
  { ssr: false, loading: () => <Skeleton className="h-72" /> },
);
const EarningsPanel = dynamic(
  () => import("@/components/provider/EarningsPanel").then((m) => m.EarningsPanel),
  { ssr: false, loading: () => <Skeleton className="h-40" /> },
);

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
