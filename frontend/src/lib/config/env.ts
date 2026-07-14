/**
 * Environment configuration — validated at module load, fail-fast.
 * Same discipline as the backend: a missing/invalid env must break the build
 * or boot with a clear message, never surface later as a mysterious runtime bug.
 *
 * Only NEXT_PUBLIC_* vars are readable in the browser. Secrets (API keys) never
 * live here — they are handled server-side via httpOnly cookies (Sesi 4).
 */

type RawEnv = {
  NEXT_PUBLIC_API_URL: string | undefined;
  NEXT_PUBLIC_RPC_URL: string | undefined;
  NEXT_PUBLIC_CHAIN_ID: string | undefined;
  NEXT_PUBLIC_ESCROW_ADDRESS: string | undefined;
  NEXT_PUBLIC_STAKING_ADDRESS: string | undefined;
  NEXT_PUBLIC_USDC_ADDRESS: string | undefined;
};

// Next.js inlines NEXT_PUBLIC_* by literal reference, so we must name each one.
const raw: RawEnv = {
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  NEXT_PUBLIC_RPC_URL: process.env.NEXT_PUBLIC_RPC_URL,
  NEXT_PUBLIC_CHAIN_ID: process.env.NEXT_PUBLIC_CHAIN_ID,
  NEXT_PUBLIC_ESCROW_ADDRESS: process.env.NEXT_PUBLIC_ESCROW_ADDRESS,
  NEXT_PUBLIC_STAKING_ADDRESS: process.env.NEXT_PUBLIC_STAKING_ADDRESS,
  NEXT_PUBLIC_USDC_ADDRESS: process.env.NEXT_PUBLIC_USDC_ADDRESS,
};

const problems: string[] = [];

function requireUrl(key: keyof RawEnv, fallback?: string): string {
  const v = raw[key] ?? fallback;
  if (!v) {
    problems.push(`${key} is required (an absolute http(s) URL).`);
    return "";
  }
  try {
    new URL(v);
  } catch {
    problems.push(`${key} must be a valid URL, got "${v}".`);
  }
  return v.replace(/\/$/, "");
}

function requireAddress(key: keyof RawEnv, fallback?: string): `0x${string}` {
  const v = raw[key] ?? fallback;
  if (!v) {
    problems.push(`${key} is required (a 0x-prefixed 20-byte address).`);
    return "0x0000000000000000000000000000000000000000";
  }
  if (!/^0x[0-9a-fA-F]{40}$/.test(v)) {
    problems.push(`${key} must be a 20-byte hex address, got "${v}".`);
  }
  return v as `0x${string}`;
}

function requireChainId(fallback = "11155111"): number {
  const v = raw.NEXT_PUBLIC_CHAIN_ID ?? fallback;
  const n = Number(v);
  if (!Number.isInteger(n) || n <= 0) {
    problems.push(`NEXT_PUBLIC_CHAIN_ID must be a positive integer, got "${v}".`);
  }
  return n;
}

// Sepolia defaults so `npm run dev` works out of the box; override via env.
export const env = {
  apiUrl: requireUrl("NEXT_PUBLIC_API_URL", "http://localhost:8000"),
  rpcUrl: requireUrl("NEXT_PUBLIC_RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com"),
  chainId: requireChainId(),
  contracts: {
    escrow: requireAddress(
      "NEXT_PUBLIC_ESCROW_ADDRESS",
      "0xd93076eb67ab21ae068c0ad7a6256ca6ba58f733",
    ),
    staking: requireAddress(
      "NEXT_PUBLIC_STAKING_ADDRESS",
      "0x72089171441d05ad2a64777177fF2864a9703822",
    ),
    usdc: requireAddress("NEXT_PUBLIC_USDC_ADDRESS", "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238"),
  },
} as const;

if (problems.length > 0) {
  // Fail loudly. In dev this surfaces in the overlay; in CI the build fails.
  throw new Error(
    `Invalid GRIDIX frontend environment:\n  - ${problems.join("\n  - ")}\n` +
      `See .env.example for the required variables.`,
  );
}

export type Env = typeof env;
