/**
 * Cost estimation for a chat turn, in USDC base units.
 *
 * The estimate is what gates the send button; the CHARGE is `cost_usdc` on the response.
 * These must never be conflated — an estimate that quietly becomes the displayed charge is
 * how a billing UI starts lying. Callers show the estimate before sending and replace it with
 * the reported cost after.
 *
 * Units, which the hand-written types got wrong twice over: the backend prices chat in
 * **decimal USDC per 1,000,000 tokens** and images in **decimal USDC per image**, both as
 * strings (`"0.05"`). The old code assumed integer micro-USDC per 1,000 tokens. Everything
 * here therefore parses through `toBaseUnits` — the app's single USDC parser — and stays in
 * bigint base units, the same unit the ledger, the escrow balance and `USDCAmount` speak.
 * No float touches a price.
 */

import { toBaseUnits } from "@/lib/format/usdc";
import { estimateTokens } from "./tokens";
import type { ChatMessage, ModelInfo } from "./contract";

const PER_MTOK = 1_000_000n;

export type CostEstimate = {
  /** USDC base units (6dp) — what the balance gate compares against. */
  base: bigint;
  promptTokens: number;
  /** What we assumed the model would write back — the dominant source of error. */
  assumedCompletionTokens: number;
};

/**
 * A price string from the API as base units, or null if it cannot be parsed.
 *
 * `toBaseUnits` throws on anything it does not recognise, and a rate card is not worth
 * crashing the models table over: an unreadable price is shown as unknown, and — because
 * `null` propagates into the gate as "cannot price this" — it never silently becomes free.
 */
export function priceToBase(usdc: string): bigint | null {
  try {
    return toBaseUnits(usdc);
  } catch {
    return null;
  }
}

/** What one image costs, in base units. Null when the model's price is unreadable. */
export function imagePriceBase(model: ModelInfo | undefined): bigint | null {
  return model ? priceToBase(model.usdc_per_image) : null;
}

/**
 * Estimate the cost of sending `messages` to `model`.
 *
 * Output length is unknowable before generation, so we price the worst case the caller has
 * allowed (`maxTokens`). That over-estimates, deliberately: the gate should refuse a request
 * the balance might not cover rather than let it fail at the node after the user has waited.
 *
 * Division rounds UP for the same reason — a gate that rounds a price down to zero is a gate
 * that lets an unaffordable request through.
 */
export function estimateChatCost(
  model: ModelInfo | undefined,
  messages: ChatMessage[],
  maxTokens: number,
): CostEstimate {
  const promptTokens = estimateTokens(messages.map((m) => m.content).join(" "));
  const inPerMtok = model ? priceToBase(model.input_usdc_per_mtok) : null;
  const outPerMtok = model ? priceToBase(model.output_usdc_per_mtok) : null;

  const numerator =
    BigInt(promptTokens) * (inPerMtok ?? 0n) + BigInt(maxTokens) * (outPerMtok ?? 0n);

  return {
    base: divCeil(numerator, PER_MTOK),
    promptTokens,
    assumedCompletionTokens: maxTokens,
  };
}

/** Ceiling division on bigints — no float, no silent truncation to zero. */
function divCeil(numerator: bigint, denominator: bigint): bigint {
  if (numerator <= 0n) return 0n;
  return (numerator + denominator - 1n) / denominator;
}
