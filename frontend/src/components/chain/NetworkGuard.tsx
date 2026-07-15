"use client";

import { useAccount, useBlockNumber, useChainId, useSwitchChain } from "wagmi";
import { activeChain } from "@/lib/chain/config";
import { Button } from "@/components/ui/Button";

/**
 * Network guard (Sesi 5.2 / 13.5). Blocks on-chain actions with a clear reason
 * when the wallet is on the wrong chain, and warns — without breaking — when the
 * chain RPC is unreachable, so on-chain reads/writes can't silently misbehave.
 * Children render only when connected AND on the right chain.
 */
export function NetworkGuard({ children }: { children: React.ReactNode }) {
  const { isConnected } = useAccount();
  const chainId = useChainId();
  const { switchChain, isPending } = useSwitchChain();
  // A lightweight liveness probe against the configured RPC.
  const block = useBlockNumber({ query: { enabled: isConnected, retry: 1 } });

  if (!isConnected) return <>{children}</>;

  if (chainId !== activeChain.id) {
    return (
      <div className="rounded-[var(--radius-md)] border border-[#ffab3d55] bg-[#ffab3d1a] p-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-sm font-[var(--font-display)] font-semibold text-[var(--color-warning)]">
              Wrong network
            </div>
            <p className="mt-1 text-sm text-[var(--color-ink-soft)]">
              GRIDIX settles on {activeChain.name}. Switch networks to deposit or withdraw.
            </p>
          </div>
          <Button
            size="sm"
            onClick={() => switchChain({ chainId: activeChain.id })}
            loading={isPending}
          >
            Switch to {activeChain.name}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {block.isError && (
        <div
          role="status"
          className="rounded-[var(--radius-md)] border border-[#ff5c5c55] bg-[#ff5c5c14] p-3 text-sm text-[var(--color-ink-soft)]"
        >
          <span className="font-medium text-[var(--color-danger)]">
            Can&apos;t reach the {activeChain.name} RPC.
          </span>{" "}
          On-chain balances may be stale and transactions could fail. Check your wallet&apos;s
          network connection before depositing or withdrawing.
        </div>
      )}
      {children}
    </div>
  );
}
