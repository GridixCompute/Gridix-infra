/** Minimal ABIs for the functions/events the frontend actually uses. */

export const escrowAbi = [
  {
    type: "function",
    name: "balanceOf",
    stateMutability: "view",
    inputs: [{ name: "developer", type: "address" }],
    outputs: [{ type: "uint256" }],
  },
  {
    type: "function",
    name: "deposit",
    stateMutability: "nonpayable",
    inputs: [{ name: "amount", type: "uint256" }],
    outputs: [],
  },
  {
    type: "function",
    name: "withdraw",
    stateMutability: "nonpayable",
    inputs: [{ name: "amount", type: "uint256" }],
    outputs: [],
  },
  {
    type: "function",
    name: "token",
    stateMutability: "view",
    inputs: [],
    outputs: [{ type: "address" }],
  },
  {
    type: "event",
    name: "Deposit",
    inputs: [
      { name: "developer", type: "address", indexed: true },
      { name: "amount", type: "uint256", indexed: false },
    ],
  },
  {
    type: "event",
    name: "Withdrawal",
    inputs: [
      { name: "developer", type: "address", indexed: true },
      { name: "amount", type: "uint256", indexed: false },
    ],
  },
] as const;

export const stakingAbi = [
  {
    type: "function",
    name: "stakeOf",
    stateMutability: "view",
    inputs: [{ name: "provider", type: "address" }],
    outputs: [{ type: "uint256" }],
  },
  {
    type: "function",
    name: "earningsOf",
    stateMutability: "view",
    inputs: [{ name: "provider", type: "address" }],
    outputs: [{ type: "uint256" }],
  },
  {
    type: "function",
    name: "unstakingOf",
    stateMutability: "view",
    inputs: [{ name: "provider", type: "address" }],
    outputs: [
      { name: "amount", type: "uint256" },
      { name: "unlockAt", type: "uint256" },
    ],
  },
  {
    type: "function",
    name: "disputeOf",
    stateMutability: "view",
    inputs: [{ name: "provider", type: "address" }],
    outputs: [
      { name: "amount", type: "uint256" },
      { name: "evidenceHash", type: "bytes32" },
      { name: "open", type: "bool" },
    ],
  },
  {
    type: "function",
    name: "minStake",
    stateMutability: "view",
    inputs: [],
    outputs: [{ type: "uint256" }],
  },
  {
    type: "function",
    name: "cooldownPeriod",
    stateMutability: "view",
    inputs: [],
    outputs: [{ type: "uint256" }],
  },
  {
    type: "function",
    name: "hasMinimumStake",
    stateMutability: "view",
    inputs: [{ name: "provider", type: "address" }],
    outputs: [{ type: "bool" }],
  },
  {
    type: "function",
    name: "stake",
    stateMutability: "nonpayable",
    inputs: [{ name: "amount", type: "uint256" }],
    outputs: [],
  },
  {
    type: "function",
    name: "unstake",
    stateMutability: "nonpayable",
    inputs: [{ name: "amount", type: "uint256" }],
    outputs: [],
  },
  {
    type: "function",
    name: "completeUnstake",
    stateMutability: "nonpayable",
    inputs: [],
    outputs: [],
  },
  {
    type: "function",
    name: "withdraw",
    stateMutability: "nonpayable",
    inputs: [],
    outputs: [],
  },
] as const;

export const erc20Abi = [
  {
    type: "function",
    name: "balanceOf",
    stateMutability: "view",
    inputs: [{ name: "account", type: "address" }],
    outputs: [{ type: "uint256" }],
  },
  {
    type: "function",
    name: "allowance",
    stateMutability: "view",
    inputs: [
      { name: "owner", type: "address" },
      { name: "spender", type: "address" },
    ],
    outputs: [{ type: "uint256" }],
  },
  {
    type: "function",
    name: "approve",
    stateMutability: "nonpayable",
    inputs: [
      { name: "spender", type: "address" },
      { name: "amount", type: "uint256" },
    ],
    outputs: [{ type: "bool" }],
  },
  {
    type: "function",
    name: "decimals",
    stateMutability: "view",
    inputs: [],
    outputs: [{ type: "uint8" }],
  },
] as const;
