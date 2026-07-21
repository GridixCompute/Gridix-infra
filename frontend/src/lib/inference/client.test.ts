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

describe("streamChatCompletion", () => {
  const encoder = new TextEncoder();
  const frame = (payload: unknown) => `data: ${JSON.stringify(payload)}\n\n`;

  const chunk = (text: string) => ({
    id: "c",
    object: "chat.completion.chunk",
    created: 0,
    model: "llama-3.1-8b",
    choices: [{ index: 0, delta: { content: text }, finish_reason: null }],
  });
  const usageFrame = {
    id: "c",
    object: "chat.completion.chunk",
    created: 0,
    model: "llama-3.1-8b",
    choices: [],
    usage: { prompt_tokens: 10, completion_tokens: 2, total_tokens: 12 },
    cost_usdc: "0.000105",
    provider_id: "00000000-0000-0000-0000-000000000000",
  };

  const REQUEST = {
    model: "llama-3.1-8b",
    messages: [{ role: "user" as const, content: "hi" }],
    temperature: 1,
    stream: true,
    data_tier: "public" as const,
  };

  /** A streaming Response whose body emits `parts`, then optionally never ends. */
  function streamingResponse(parts: string[], opts: { endless?: boolean } = {}) {
    const body = new ReadableStream<Uint8Array>({
      async start(controller) {
        for (const part of parts) controller.enqueue(encoder.encode(part));
        if (!opts.endless) controller.close();
      },
    });
    return new Response(body, {
      status: 200,
      headers: { "content-type": "text/event-stream" },
    });
  }

  it("asks the backend to stream, whatever the caller passed", async () => {
    fetchMock.mockResolvedValue(streamingResponse([frame(chunk("a")), "data: [DONE]\n\n"]));
    const { streamChatCompletion } = await import("./client");

    const seen = [];
    for await (const e of streamChatCompletion({ ...REQUEST, stream: false })) seen.push(e);

    const init = fetchMock.mock.calls[0]?.[1];
    expect(JSON.parse(init.body).stream).toBe(true);
    expect(init.headers.Accept).toBe("text/event-stream");
    expect(seen).toEqual([{ kind: "delta", content: "a" }]);
  });

  it("yields deltas then usage, with cost as a string", async () => {
    fetchMock.mockResolvedValue(
      streamingResponse([
        frame(chunk("Hel")),
        frame(chunk("lo")),
        frame(usageFrame),
        "data: [DONE]\n\n",
      ]),
    );
    const { streamChatCompletion } = await import("./client");

    const seen = [];
    for await (const e of streamChatCompletion(REQUEST)) seen.push(e);

    expect(seen.filter((e) => e.kind === "delta").map((e) => e.content)).toEqual(["Hel", "lo"]);
    const usage = seen.find((e) => e.kind === "usage");
    expect(usage).toBeDefined();
    expect(usage?.costUsdc).toBe("0.000105");
    expect(usage?.usage.completion_tokens).toBe(2);
  });

  it("maps a pre-stream failure to a status error", async () => {
    // Before the first byte the backend still answers with a normal JSON error, so the
    // status mapping applies. After bytes flow it reports failure in-band instead.
    fetchMock.mockResolvedValue(new Response("{}", { status: 402 }));
    const { streamChatCompletion } = await import("./client");

    await expect(
      (async () => {
        for await (const _ of streamChatCompletion(REQUEST)) void _;
      })(),
    ).rejects.toMatchObject({ kind: "insufficient_balance" });
  });

  it("PASSES THE ABORT SIGNAL TO FETCH — the whole cancel chain hangs off this", async () => {
    // The coordinator learns a client is gone by the connection closing. If the signal
    // never reaches fetch, Cancel becomes a UI illusion: the node keeps generating and the
    // hold is settled for tokens nobody was shown.
    fetchMock.mockResolvedValue(streamingResponse([frame(chunk("a"))], { endless: true }));
    const { streamChatCompletion } = await import("./client");

    const controller = new AbortController();
    const gen = streamChatCompletion(REQUEST, controller.signal);
    await gen.next();

    const init = fetchMock.mock.calls[0]?.[1];
    expect(init.signal).toBeDefined();
    expect(init.signal).toBe(controller.signal);

    expect(init.signal.aborted).toBe(false);
    controller.abort();
    expect(init.signal.aborted).toBe(true);

    await gen.return(undefined);
  });

  it("stops reading once the signal aborts", async () => {
    fetchMock.mockResolvedValue(
      streamingResponse([frame(chunk("a")), frame(chunk("b"))], { endless: true }),
    );
    const { streamChatCompletion } = await import("./client");

    const controller = new AbortController();
    const gen = streamChatCompletion(REQUEST, controller.signal);
    const first = await gen.next();
    expect(first.value).toEqual({ kind: "delta", content: "a" });

    controller.abort();
    // The generator must end rather than sit on a connection nobody is listening to.
    expect((await gen.next()).done).toBe(true);
  });

  it("closes the response body when the consumer stops early", async () => {
    // Abandoning the stream must close the connection, not just stop reading it.
    let cancelled = false;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(frame(chunk("a"))));
      },
      cancel() {
        cancelled = true;
      },
    });
    fetchMock.mockResolvedValue(
      new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }),
    );
    const { streamChatCompletion } = await import("./client");

    const gen = streamChatCompletion(REQUEST);
    await gen.next();
    await gen.return(undefined);

    expect(cancelled).toBe(true);
  });
});
