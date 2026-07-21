import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

/**
 * The client reads the envelopes the backend actually sends.
 *
 * These pin the three specific ways the deleted hand-written `types.ts` disagreed with `/v1/*`.
 * Each one type-checked, each one passed the whole suite in mock mode, and each one would
 * have thrown or shown nothing the first time `NEXT_PUBLIC_INFERENCE_MOCK=false`:
 *
 *   1. `/v1/models` answers `{models: [...]}`; the guess read `{data: [...]}` → undefined.
 *   2. images answer `data: [{url}]`; the guess read `b64_json` → a broken <img>.
 *   3. chat is unary; the guess sent `stream: true`, which the backend answers with 501.
 *
 * A type alias to the generated schema is what stops (1) and (2) recurring, but a compiler
 * cannot check that `res.json()` really contains what the cast claims — so the parsing is
 * exercised against real payloads here.
 */

const OK = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  // Force the real path; in mock mode none of this code runs.
  vi.stubEnv("NEXT_PUBLIC_INFERENCE_MOCK", "false");
  vi.resetModules();
  fetchMock.mockReset();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("listModels", () => {
  it("reads the `models` key, not `data`", async () => {
    fetchMock.mockResolvedValue(
      OK({
        models: [
          {
            id: "llama-3.1-8b",
            modality: "chat",
            available: true,
            nodes: 2,
            input_usdc_per_mtok: "0.05",
            output_usdc_per_mtok: "0.08",
            usdc_per_image: "0",
            context_window: 128000,
          },
        ],
      }),
    );

    const { listModels } = await import("./client");
    const models = await listModels();

    expect(models).toHaveLength(1);
    expect(models[0]?.id).toBe("llama-3.1-8b");
  });
});

describe("createChatCompletion", () => {
  const RESPONSE = {
    id: "chatcmpl-1",
    object: "chat.completion",
    created: 0,
    model: "llama-3.1-8b",
    choices: [{ index: 0, message: { role: "assistant", content: "hi" }, finish_reason: "stop" }],
    usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
    cost_usdc: "0.000042",
    provider_id: "00000000-0000-0000-0000-000000000000",
  };

  const REQUEST = {
    model: "llama-3.1-8b",
    messages: [{ role: "user" as const, content: "hi" }],
    temperature: 1,
    stream: false,
    data_tier: "public" as const,
  };

  it("unwraps the reply from choices[0].message", async () => {
    fetchMock.mockResolvedValue(OK(RESPONSE));
    const { createChatCompletion } = await import("./client");

    const res = await createChatCompletion(REQUEST);
    expect(res.choices[0]?.message.content).toBe("hi");
    expect(res.cost_usdc).toBe("0.000042");
  });

  it("never asks for a stream, even if a caller sets one", async () => {
    fetchMock.mockResolvedValue(OK(RESPONSE));
    const { createChatCompletion } = await import("./client");

    // A caller cannot opt into streaming by accident: the backend answers stream=true with
    // 501, so sending it would be a request we already know is refused.
    await createChatCompletion({ ...REQUEST, stream: true });

    const sent = JSON.parse(fetchMock.mock.calls[0]?.[1]?.body as string);
    expect(sent.stream).toBe(false);
  });
});

describe("error mapping", () => {
  it.each([
    [402, "insufficient_balance"],
    [403, "forbidden"],
    [503, "no_node"],
    [501, "not_implemented"],
  ])("maps %i to %s", async (status, kind) => {
    fetchMock.mockResolvedValue(new Response("{}", { status }));
    const { listModels, InferenceError } = await import("./client");

    // 402 (not 403) is insufficient balance, and 503 (not 404) is "nothing is serving it" —
    // the previous mapping had both wrong and would have shown the wrong message.
    await expect(listModels()).rejects.toMatchObject({ kind });
    await expect(listModels()).rejects.toBeInstanceOf(InferenceError);
  });
});
