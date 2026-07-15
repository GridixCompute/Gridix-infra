"use client";

import { useState } from "react";
import { waitForTransactionReceipt } from "wagmi/actions";
import { wagmiConfig } from "./config";
import type { TxState } from "@/components/domain/TxStatus";

/** Turn a raw wallet/chain error into one friendly line. */
export function friendlyTxError(e: unknown): string {
  const msg = e instanceof Error ? e.message : "Transaction failed.";
  if (/user rejected|denied/i.test(msg)) return "You rejected the transaction in your wallet.";
  if (/insufficient funds/i.test(msg)) return "Not enough ETH to pay for gas.";
  return msg.split("\n")[0]!;
}

/**
 * Shared on-chain-action lifecycle (Sesi 5.4): signing → pending (hash +
 * explorer) → confirmed, never showing success before the chain confirms.
 * `send` broadcasts one tx and waits for its receipt; a multi-step action
 * (e.g. approve then stake) calls it more than once inside `run`.
 */
export function useChainAction() {
  const [tx, setTx] = useState<TxState>("idle");
  const [hash, setHash] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);
  const busy = tx === "signing" || tx === "pending";

  async function send(write: () => Promise<`0x${string}`>): Promise<void> {
    setTx("signing");
    const h = await write();
    setHash(h);
    setTx("pending");
    await waitForTransactionReceipt(wagmiConfig, { hash: h });
  }

  async function run(
    action: (send: (w: () => Promise<`0x${string}`>) => Promise<void>) => Promise<void>,
  ) {
    setError(null);
    try {
      await action(send);
      setTx("confirmed");
    } catch (e) {
      setTx("failed");
      setError(friendlyTxError(e));
    }
  }

  function reset() {
    setTx("idle");
    setHash(undefined);
    setError(null);
  }

  return { tx, hash, error, busy, run, reset };
}
