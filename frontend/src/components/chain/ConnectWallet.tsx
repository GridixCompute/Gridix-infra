"use client";

import { useAccount, useConnect, useDisconnect } from "wagmi";
import { Button } from "@/components/ui/Button";
import { AddressDisplay } from "@/components/domain/AddressDisplay";

/** Connect / disconnect an injected wallet (Session 5.1). */
export function ConnectWallet() {
  const { address, isConnected } = useAccount();
  const { connect, connectors, isPending } = useConnect();
  const { disconnect } = useDisconnect();

  if (isConnected && address) {
    return (
      <div className="flex items-center gap-3">
        <span className="flex items-center gap-2 rounded-full border border-[var(--color-hairline-strong)] bg-[var(--color-panel)] px-3 py-1.5 text-sm">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-success)]" aria-hidden="true" />
          <AddressDisplay value={address} />
        </span>
        <Button variant="ghost" size="sm" onClick={() => disconnect()}>
          Disconnect
        </Button>
      </div>
    );
  }

  const injected = connectors[0];
  return (
    <Button
      onClick={() => injected && connect({ connector: injected })}
      loading={isPending}
      disabled={!injected}
    >
      {injected ? "Connect wallet" : "No wallet detected"}
    </Button>
  );
}
