"use client";

import { useAccount } from "wagmi";
import { writeContract } from "wagmi/actions";
import { wagmiConfig, contracts } from "@/lib/chain/config";
import { stakingAbi } from "@/lib/chain/abis";
import { useProviderEarnings } from "@/lib/chain/stakingHooks";
import { useChainAction } from "@/lib/chain/useChainAction";
import { Button } from "@/components/ui/Button";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { TxStatus } from "@/components/domain/TxStatus";

/**
 * Withdraw settled earnings (Sesi 11.4). The coordinator credits earnings via
 * settleBatch on-chain; the provider withdraws them to its own wallet, paying
 * its own gas. `withdraw()` takes the full balance — no partial withdrawals.
 */
export function EarningsPanel() {
  const { address, isConnected } = useAccount();
  const earnings = useProviderEarnings(address);
  const { tx, hash, error, busy, run } = useChainAction();

  const balance = (earnings.data as bigint | undefined) ?? 0n;
  const hasEarnings = balance > 0n;

  async function withdraw() {
    await run(async (send) => {
      await send(() =>
        writeContract(wagmiConfig, {
          address: contracts.staking,
          abi: stakingAbi,
          functionName: "withdraw",
        }),
      );
      void earnings.refetch();
    });
  }

  return (
    <div className="space-y-4">
      <div>
        <div className="text-xs tracking-wide text-[var(--color-ink-faint)] uppercase">
          Withdrawable earnings
        </div>
        <div className="mt-1 text-2xl">
          {isConnected ? (
            <USDCAmount base={balance} tone="credit" />
          ) : (
            <span className="text-sm text-[var(--color-ink-faint)]">Connect to see earnings.</span>
          )}
        </div>
      </div>

      <Button
        className="w-full"
        onClick={withdraw}
        loading={busy}
        disabled={!isConnected || !hasEarnings}
      >
        {busy ? "Withdrawing…" : "Withdraw all"}
      </Button>

      {!hasEarnings && isConnected && (
        <p className="text-xs text-[var(--color-ink-faint)]">
          Earnings accrue as your node completes jobs and the coordinator settles the batch
          on-chain. They&apos;ll appear here to withdraw.
        </p>
      )}

      {tx !== "idle" && (
        <div className="flex flex-col gap-1">
          <TxStatus state={tx} hash={hash} />
          {tx === "confirmed" && (
            <span className="text-sm text-[var(--color-success)]">Withdrawn to your wallet.</span>
          )}
          {error && <span className="text-sm text-[var(--color-danger)]">{error}</span>}
        </div>
      )}
    </div>
  );
}
