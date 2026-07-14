"use client";

import { useReadContract } from "wagmi";
import { escrowAbi, erc20Abi } from "./abis";
import { contracts } from "./config";

/** On-chain escrow balance (deposited USDC) for an address. Base units (bigint). */
export function useEscrowBalance(address?: `0x${string}`) {
  return useReadContract({
    address: contracts.escrow,
    abi: escrowAbi,
    functionName: "balanceOf",
    args: address ? [address] : undefined,
    query: { enabled: !!address, refetchInterval: 8000 },
  });
}

/** USDC held in the user's own wallet (available to deposit). */
export function useWalletUsdc(address?: `0x${string}`) {
  return useReadContract({
    address: contracts.usdc,
    abi: erc20Abi,
    functionName: "balanceOf",
    args: address ? [address] : undefined,
    query: { enabled: !!address, refetchInterval: 8000 },
  });
}

/** Current USDC allowance the escrow has to pull from the wallet. */
export function useAllowance(owner?: `0x${string}`) {
  return useReadContract({
    address: contracts.usdc,
    abi: erc20Abi,
    functionName: "allowance",
    args: owner ? [owner, contracts.escrow] : undefined,
    query: { enabled: !!owner },
  });
}
