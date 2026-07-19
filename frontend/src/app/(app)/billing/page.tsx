"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useAccount } from "wagmi";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { ConnectWallet } from "@/components/chain/ConnectWallet";
import { NetworkGuard } from "@/components/chain/NetworkGuard";

// Lazy-load the wallet write path (wagmi/actions) so it ships only when a
// signed-in developer opens the deposit/withdraw panel (Session 13.4).
const DepositWithdraw = dynamic(
  () => import("@/components/chain/DepositWithdraw").then((m) => m.DepositWithdraw),
  { ssr: false, loading: () => <Skeleton className="h-56" /> },
);
import { PeriodSummary } from "@/components/billing/PeriodSummary";
import { Reconciliation } from "@/components/billing/Reconciliation";
import { LedgerHistory } from "@/components/billing/LedgerHistory";
import { useEscrowBalance, useWalletUsdc } from "@/lib/chain/hooks";
import { cn } from "@/lib/utils/cn";

export default function BillingPage() {
  const { address, isConnected } = useAccount();
  const escrow = useEscrowBalance(address);
  const wallet = useWalletUsdc(address);
  const escrowBase = isConnected ? ((escrow.data as bigint | undefined) ?? 0n) : null;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
            Billing & ledger
          </h1>
          <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
            Every charge traced to the ledger, reconciled against on-chain escrow.
          </p>
        </div>
        <ConnectWallet />
      </div>

      {/* Period totals — backend ledger, no wallet needed. */}
      <PeriodSummary />

      {/* On-chain vs off-chain. */}
      <Reconciliation escrowBase={escrowBase} />

      {/* Fund escrow — wallet-gated. */}
      <NetworkGuard>
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Move funds</CardTitle>
              {isConnected && (
                <span className="text-xs text-[var(--color-ink-faint)]">
                  Wallet USDC:{" "}
                  <USDCAmount base={(wallet.data as bigint | undefined) ?? 0n} tone="muted" />
                </span>
              )}
            </div>
          </CardHeader>
          <CardBody>
            {isConnected ? (
              <MoveFunds />
            ) : (
              <p className="text-sm text-[var(--color-ink-faint)]">
                Connect your wallet to deposit USDC into escrow or withdraw what&apos;s available.
              </p>
            )}
          </CardBody>
        </Card>
      </NetworkGuard>

      {/* Full ledger history. */}
      <LedgerHistory />
    </div>
  );
}

function MoveFunds() {
  const [tab, setTab] = useState<"deposit" | "withdraw">("deposit");
  return (
    <div className="space-y-5">
      <div className="inline-flex rounded-[var(--radius-sm)] border border-[var(--color-hairline)] p-0.5">
        {(["deposit", "withdraw"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "rounded-[var(--radius-xs)] px-4 py-1.5 text-sm capitalize transition-colors",
              tab === t
                ? "bg-[var(--color-panel-raised)] text-[var(--color-ink)]"
                : "text-[var(--color-ink-faint)] hover:text-[var(--color-ink)]",
            )}
          >
            {t}
          </button>
        ))}
      </div>
      <div className="max-w-sm">
        <DepositWithdraw mode={tab} />
      </div>
    </div>
  );
}
