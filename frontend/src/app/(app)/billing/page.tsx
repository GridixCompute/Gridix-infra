"use client";

import { useState } from "react";
import { useAccount } from "wagmi";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { ConnectWallet } from "@/components/chain/ConnectWallet";
import { NetworkGuard } from "@/components/chain/NetworkGuard";
import { DepositWithdraw } from "@/components/chain/DepositWithdraw";
import { EmptyState } from "@/components/ui/States";
import { useEscrowBalance, useWalletUsdc } from "@/lib/chain/hooks";
import { useJobs } from "@/lib/hooks/useJobs";
import { toBaseUnits } from "@/lib/format/usdc";
import { isTerminal } from "@/lib/api/types";
import { cn } from "@/lib/utils/cn";

export default function BillingPage() {
  const { address, isConnected } = useAccount();
  const escrow = useEscrowBalance(address);
  const wallet = useWalletUsdc(address);
  const { data: jobs } = useJobs({ limit: 200 });

  // Held = worst-case escrow of jobs still running (from the backend ledger).
  const heldBase = (jobs ?? [])
    .filter((j) => !isTerminal(j.status) && j.escrow_amount != null)
    .reduce((sum, j) => sum + toBaseUnits(j.escrow_amount as number), 0n);

  const escrowBase = (escrow.data as bigint | undefined) ?? 0n;
  const availableBase = escrowBase > heldBase ? escrowBase - heldBase : 0n;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
            Billing & balance
          </h1>
          <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
            Fund your escrow on-chain. No balance, no compute — the contract enforces it.
          </p>
        </div>
        <ConnectWallet />
      </div>

      {!isConnected ? (
        <Card>
          <EmptyState
            title="Connect your wallet"
            description="Connect an Ethereum wallet to view your on-chain escrow balance and deposit USDC to run jobs."
          />
        </Card>
      ) : (
        <NetworkGuard>
          <div className="grid gap-4 sm:grid-cols-3">
            <BalanceCard
              label="Available"
              base={availableBase}
              tone="signal"
              hint="Escrow you can spend on new jobs."
            />
            <BalanceCard
              label="Held by active jobs"
              base={heldBase}
              hint="Escrowed against jobs still running."
            />
            <BalanceCard
              label="In escrow (on-chain)"
              base={escrowBase}
              hint="Total deposited to GridixEscrow."
            />
          </div>

          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>Move funds</CardTitle>
                <span className="text-xs text-[var(--color-ink-faint)]">
                  Wallet USDC:{" "}
                  <USDCAmount base={(wallet.data as bigint | undefined) ?? 0n} tone="muted" />
                </span>
              </div>
            </CardHeader>
            <CardBody>
              <MoveFunds />
            </CardBody>
          </Card>
        </NetworkGuard>
      )}
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

function BalanceCard({
  label,
  base,
  hint,
  tone,
}: {
  label: string;
  base: bigint;
  hint: string;
  tone?: "signal";
}) {
  return (
    <Card>
      <CardBody>
        <div className="text-xs tracking-wide text-[var(--color-ink-faint)] uppercase">{label}</div>
        <div className="mt-1.5 text-xl">
          <USDCAmount base={base} tone={tone === "signal" ? "signal" : "default"} />
        </div>
        <p className="mt-1 text-xs text-[var(--color-ink-faint)]">{hint}</p>
      </CardBody>
    </Card>
  );
}
