"use client";

import { useAccount, useChainId, useSwitchChain } from "wagmi";
import { activeChain } from "@/lib/chain/config";
import { Button } from "@/components/ui/Button";

/**
 * Network guard (Sesi 5.2). If the wallet is on the wrong chain, show a banner
 * and block on-chain actions until the user switches. Children render only when
 * connected AND on the right chain.
 */
export function NetworkGuard({ children }: { children: React.ReactNode }) {
  const { isConnected } = useAccount();
  const chainId = useChainId();
  const { switchChain, isPending } = useSwitchChain();

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

  return <>{children}</>;
}
