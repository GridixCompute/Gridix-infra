/**
 * Cost estimation for a chat turn (Sesi 4.3 / 4.5).
 *
 * The estimate is what gates the send button; the CHARGE is whatever the backend reports in
 * the stream's `usage` frame. These must never be conflated — an estimate that quietly
 * becomes the displayed charge is how a billing UI starts lying. Callers show the estimate
 * before sending and replace it with the reported cost after.
 *
 * ⚠️ Rates come from `InferenceModel`, which today is mock data (see `./mock`). The tokenizer
 * is a length heuristic, not the node's. Both are wrong in ways only the real backend fixes.
 */

import { estimateTokens } from "./mock";
import type { ChatMessage, InferenceModel } from "./types";

export type CostEstimate = {
  /** Micro-USDC (6dp), the unit the rate card and the ledger both use. */
  micro: number;
  promptTokens: number;
  /** What we assumed the model would write back — the dominant source of error. */
  assumedCompletionTokens: number;
};

/**
 * Estimate the cost of sending `messages` to `model`.
 *
 * Output length is unknowable before generation, so we price the worst case the caller has
 * allowed (`maxTokens`). That over-estimates, deliberately: the gate should refuse a request
 * the balance might not cover rather than let it fail at the node after the user has waited.
 */
export function estimateChatCost(
  model: InferenceModel | undefined,
  messages: ChatMessage[],
  maxTokens: number,
): CostEstimate {
  const promptTokens = estimateTokens(messages.map((m) => m.content).join(" "));
  const inRate = model?.pricePer1kInput ?? 0;
  const outRate = model?.pricePer1kOutput ?? 0;
  return {
    micro: Math.round((promptTokens / 1000) * inRate + (maxTokens / 1000) * outRate),
    promptTokens,
    assumedCompletionTokens: maxTokens,
  };
}

/** Micro-USDC (6dp) → the base units `USDCAmount` and the ledger speak. */
export function microToBase(micro: number): bigint {
  return BigInt(Math.round(micro));
}
