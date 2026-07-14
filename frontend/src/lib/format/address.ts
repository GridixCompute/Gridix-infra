import { env } from "@/lib/config/env";

/** Truncate a 0x address / tx hash for display: 0x1234…abcd. */
export function truncateHex(value: string, lead = 6, tail = 4): string {
  if (!value.startsWith("0x") || value.length <= lead + tail + 2) return value;
  return `${value.slice(0, lead)}…${value.slice(-tail)}`;
}

const EXPLORERS: Record<number, string> = {
  1: "https://etherscan.io",
  11155111: "https://sepolia.etherscan.io",
};

function explorerBase(): string {
  return EXPLORERS[env.chainId] ?? EXPLORERS[11155111]!;
}

export function explorerAddressUrl(address: string): string {
  return `${explorerBase()}/address/${address}`;
}

export function explorerTxUrl(txHash: string): string {
  return `${explorerBase()}/tx/${txHash}`;
}
