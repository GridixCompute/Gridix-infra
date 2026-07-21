/**
 * A token-count heuristic, used only to price a request BEFORE it is sent.
 *
 * Lives apart from the mock because the pre-send estimate is a real code path that runs
 * against the real backend too — `pricing.ts` importing it from `./mock` made the production
 * balance gate depend on a module that exists to be deleted.
 *
 * It is a length heuristic, not a tokenizer. The authoritative count is `usage` on the
 * response, which is what the developer is actually billed on.
 */
export function estimateTokens(text: string): number {
  return Math.max(1, Math.ceil(text.length / 4));
}
