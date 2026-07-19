import { createConfig, http } from "wagmi";
import { sepolia } from "wagmi/chains";
import { injected } from "wagmi/connectors";
import { env } from "@/lib/config/env";

/**
 * wagmi config (Session 5.1). Single injected connector (MetaMask & friends), RPC
 * from validated env. GRIDIX settles on Sepolia; NEXT_PUBLIC_CHAIN_ID must be
 * 11155111 to match (env validation defaults to it).
 */
export const activeChain = sepolia;

export const wagmiConfig = createConfig({
  chains: [sepolia],
  connectors: [injected()],
  transports: { [sepolia.id]: http(env.rpcUrl) },
  ssr: true,
});

// Contracts the app transacts against (escrow + staking + their USDC token).
export const contracts = {
  escrow: env.contracts.escrow,
  staking: env.contracts.staking,
  usdc: env.contracts.usdc,
} as const;

declare module "wagmi" {
  interface Register {
    config: typeof wagmiConfig;
  }
}
