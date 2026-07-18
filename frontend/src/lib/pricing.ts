/**
 * Client-side cost estimate (Session 7.3). Mirrors the backend pricing model
 * (app/pricing.py) so the number shown before submit is close to what settles.
 * The backend remains the source of truth at settlement — this is an estimate.
 *
 * These constants mirror backend config DEFAULTS. If an operator overrides them
 * server-side, the estimate can drift; the escrow the API returns is exact.
 */
const USDC_SCALE = 1_000_000n;

// backend defaults: base_job_price=1.0 USDC per cpu-core-minute, GPU ×4,
// protocol_fee_bps=250 (2.5%).
const BASE_PRICE_BASE = 1_000_000n; // 1.0 USDC in base units
const GPU_MULTIPLIER = 4n;
const PROTOCOL_FEE_BPS = 250n;

export type CostEstimate = {
  /** Worst-case compute cost = what gets escrowed. */
  computeBase: bigint;
  /** Protocol fee on top (charged at settlement). */
  feeBase: bigint;
  /** compute + fee. */
  totalBase: bigint;
};

/**
 * Escrow/compute estimate. Uses integer math on base units. The backend escrows
 * the compute cost (no fee); the fee is applied at settlement, so we surface
 * both so the developer sees the full worst case.
 */
export function estimateCost(input: {
  cpuCores: number;
  gpu: boolean;
  timeoutSeconds: number;
}): CostEstimate {
  const cpu = BigInt(Math.max(1, Math.floor(input.cpuCores)));
  const seconds = BigInt(Math.max(0, Math.floor(input.timeoutSeconds)));
  const mult = input.gpu ? GPU_MULTIPLIER : 1n;

  // base * cpu * mult * (seconds / 60). Divide last to preserve precision.
  const computeBase = (BASE_PRICE_BASE * cpu * mult * seconds) / 60n;
  const feeBase = (computeBase * PROTOCOL_FEE_BPS) / 10_000n;
  return { computeBase, feeBase, totalBase: computeBase + feeBase };
}

export { USDC_SCALE };
