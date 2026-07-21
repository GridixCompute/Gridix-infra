import { describe, it, expect } from "vitest";
import { mockChatStream, MOCK_MODELS } from "./mock";
import { toBaseUnits } from "@/lib/format/usdc";
import type { ChatCompletionRequest } from "./contract";

/**
 * The mock is what the playground runs today, so it has to behave like the real stream —
 * not merely compile. #34's lesson is that a mock which agrees with a guess instead of the
 * API hides a broken client indefinitely; the guard against that is typing it against the
 * generated schema (the compiler's job) AND making it emit the same event sequence the SSE
 * parser produces (this file's job).
 */

const REQUEST: ChatCompletionRequest = {
  model: MOCK_MODELS[0]!.id,
  messages: [{ role: "user", content: "hi" }],
  temperature: 1,
  stream: true,
  data_tier: "public",
};

describe("mockChatStream", () => {
  it("emits deltas progressively, then finish, then usage", async () => {
    const kinds: string[] = [];
    let firstDeltaAt = -1;
    for await (const event of mockChatStream(REQUEST)) {
      if (event.kind === "delta" && firstDeltaAt === -1) firstDeltaAt = kinds.length;
      kinds.push(event.kind);
    }

    expect(firstDeltaAt).toBe(0); // content starts before anything else
    expect(kinds.filter((k) => k === "delta").length).toBeGreaterThan(1);
    expect(kinds.at(-2)).toBe("finish");
    expect(kinds.at(-1)).toBe("usage");
  });

  it("reports a cost the app's USDC parser accepts", async () => {
    // A mock emitting full float precision would produce a `cost_usdc` the real backend
    // never sends and the real parser would reject — passing here, failing in production.
    let cost: string | undefined;
    for await (const event of mockChatStream(REQUEST)) {
      if (event.kind === "usage") cost = event.costUsdc;
    }
    expect(cost).toBeDefined();
    expect(() => toBaseUnits(cost!)).not.toThrow();
  });

  it("stops when the signal aborts, like a severed connection", async () => {
    // Mock mode must exercise the same cancel path as the real one, or the panel's
    // behaviour diverges the moment the flag flips.
    const controller = new AbortController();
    const seen: string[] = [];

    await expect(
      (async () => {
        for await (const event of mockChatStream(REQUEST, controller.signal)) {
          seen.push(event.kind);
          if (seen.length === 2) controller.abort();
        }
      })(),
    ).rejects.toMatchObject({ name: "AbortError" });

    expect(seen.length).toBeLessThan(10); // stopped early, did not run to completion
  });
});
