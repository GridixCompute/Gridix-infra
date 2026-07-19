/**
 * USDC formatting — CRITICAL (Session 6.6). USDC has 6 decimals, NOT 18.
 * Every parse/format of a token amount in the app goes through this single
 * module so the number in the UI equals the number on-chain, exactly.
 *
 * On-chain amounts are integers of "base units" (1 USDC = 1_000_000 units).
 * We carry them as bigint to avoid float drift, and only format at the edge.
 */

export const USDC_DECIMALS = 6;
const SCALE = 1_000_000n; // 10 ** 6

/** Parse a human string ("12.50") into base units (bigint). Throws on garbage. */
export function parseUsdc(input: string): bigint {
  const trimmed = input.trim();
  if (!/^\d*\.?\d*$/.test(trimmed) || trimmed === "" || trimmed === ".") {
    throw new Error(`"${input}" is not a valid USDC amount.`);
  }
  const [whole, frac = ""] = trimmed.split(".");
  if (frac.length > USDC_DECIMALS) {
    throw new Error(`USDC supports at most ${USDC_DECIMALS} decimal places.`);
  }
  const fracPadded = frac.padEnd(USDC_DECIMALS, "0");
  return BigInt(whole || "0") * SCALE + BigInt(fracPadded || "0");
}

/** Coerce whatever the API returns (number | string | bigint) to base units. */
export function toBaseUnits(amount: number | string | bigint): bigint {
  if (typeof amount === "bigint") return amount;
  if (typeof amount === "string") return parseUsdc(amount);
  // A JSON number from the ledger is already a decimal USDC value.
  return parseUsdc(amount.toString());
}

type FormatOptions = {
  /** Trailing "USDC". Default true. */
  symbol?: boolean;
  /** Minimum fraction digits (default 2, capped at 6). */
  minFractionDigits?: number;
  /** Thousands grouping. Default true. */
  grouping?: boolean;
};

/** Format base units (bigint) as a display string, exact to 6 decimals. */
export function formatUsdc(base: bigint, opts: FormatOptions = {}): string {
  const { symbol = true, minFractionDigits = 2, grouping = true } = opts;
  const negative = base < 0n;
  const abs = negative ? -base : base;

  const whole = abs / SCALE;
  const frac = abs % SCALE;

  let fracStr = frac.toString().padStart(USDC_DECIMALS, "0");
  // Trim trailing zeros but keep at least minFractionDigits.
  fracStr = fracStr.replace(/0+$/, "");
  while (fracStr.length < minFractionDigits) fracStr += "0";

  const wholeStr = grouping ? withGrouping(whole) : whole.toString();
  const number = fracStr ? `${wholeStr}.${fracStr}` : wholeStr;
  return `${negative ? "-" : ""}${number}${symbol ? " USDC" : ""}`;
}

/** Convenience: format an API-supplied amount directly. */
export function formatUsdcAmount(amount: number | string | bigint, opts?: FormatOptions): string {
  return formatUsdc(toBaseUnits(amount), opts);
}

function withGrouping(n: bigint): string {
  const s = n.toString();
  return s.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}
