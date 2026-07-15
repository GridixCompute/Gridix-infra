"use client";

import { useReadContract } from "wagmi";
import { stakingAbi, erc20Abi } from "./abis";
import { contracts } from "./config";

const POLL = 8000;

/** Active collateral staked by a provider. Base units (bigint). */
export function useProviderStake(address?: `0x${string}`) {
  return useReadContract({
    address: contracts.staking,
    abi: stakingAbi,
    functionName: "stakeOf",
    args: address ? [address] : undefined,
    query: { enabled: !!address, refetchInterval: POLL },
  });
}

/** Settled, provider-withdrawable earnings. Base units (bigint). */
export function useProviderEarnings(address?: `0x${string}`) {
  return useReadContract({
    address: contracts.staking,
    abi: stakingAbi,
    functionName: "earningsOf",
    args: address ? [address] : undefined,
    query: { enabled: !!address, refetchInterval: POLL },
  });
}

/** Cooling-down stake: `[amount, unlockAt]` (unlockAt is a unix seconds bigint). */
export function useUnstaking(address?: `0x${string}`) {
  return useReadContract({
    address: contracts.staking,
    abi: stakingAbi,
    functionName: "unstakingOf",
    args: address ? [address] : undefined,
    query: { enabled: !!address, refetchInterval: POLL },
  });
}

/** Held/slashed stake under dispute: `[amount, evidenceHash, open]`. */
export function useStakeDispute(address?: `0x${string}`) {
  return useReadContract({
    address: contracts.staking,
    abi: stakingAbi,
    functionName: "disputeOf",
    args: address ? [address] : undefined,
    query: { enabled: !!address, refetchInterval: POLL },
  });
}

/** Protocol-wide minimum stake required to receive jobs. */
export function useMinStake() {
  return useReadContract({
    address: contracts.staking,
    abi: stakingAbi,
    functionName: "minStake",
  });
}

/** USDC allowance the staking contract has to pull from the wallet (for stake). */
export function useStakeAllowance(owner?: `0x${string}`) {
  return useReadContract({
    address: contracts.usdc,
    abi: erc20Abi,
    functionName: "allowance",
    args: owner ? [owner, contracts.staking] : undefined,
    query: { enabled: !!owner },
  });
}
