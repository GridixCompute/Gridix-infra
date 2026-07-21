import { describe, it, expect } from "vitest";
import { chatStreamEvents, eventsFromFrame, sseFrames } from "./sse";

/**
 * The frame shapes here are copied from the backend's emission sites in
 * `api/app/streaming_chat.py`, because the generated schema cannot supply them: the route
 * declares the streamed body as `"text/event-stream": {"schema": {"type": "string"}}`, so
 * there is nothing to generate and the drift gate cannot police it.
 *
 * That makes these tests the only thing standing between this parser and the #34 failure
 * mode — a client confidently decoding a shape the backend never sends. They are written
 * against what the backend emits, not against what this parser happens to accept.
 */

/** Build a byte stream from SSE text, optionally split at arbitrary points. */
function streamOf(...parts: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(encoder.encode(part));
      controller.close();
    },
  });
}

const frame = (payload: unknown) => `data: ${JSON.stringify(payload)}\n\n`;

// The five shapes api/app/streaming_chat.py actually emits.
const ROLE_OPENER = {
  id: "chatcmpl-1",
  object: "chat.completion.chunk",
  created: 0,
  model: "llama-3.1-8b",
  choices: [{ index: 0, delta: { role: "assistant" }, finish_reason: null }],
};
const content = (text: string) => ({
  id: "chatcmpl-1",
  object: "chat.completion.chunk",
  created: 0,
  model: "llama-3.1-8b",
  choices: [{ index: 0, delta: { content: text }, finish_reason: null }],
});
const FINISH = {
  id: "chatcmpl-1",
  object: "chat.completion.chunk",
  created: 0,
  model: "llama-3.1-8b",
  choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
};
const USAGE = {
  id: "chatcmpl-1",
  object: "chat.completion.chunk",
  created: 0,
  model: "llama-3.1-8b",
  choices: [],
  usage: { prompt_tokens: 10, completion_tokens: 4, total_tokens: 14 },
  cost_usdc: "0.000105",
  provider_id: "00000000-0000-0000-0000-000000000000",
};
const ERROR = { error: { message: "The node failed to complete the request." } };

async function collect<T>(gen: AsyncGenerator<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const item of gen) out.push(item);
  return out;
}

describe("frame interpretation", () => {
  it("reads a content delta", () => {
    expect(eventsFromFrame(content("Hel"))).toEqual([{ kind: "delta", content: "Hel" }]);
  });

  it("yields nothing for the role opener", () => {
    // It carries no content. Emitting an empty delta would cost a render per stream and
    // show nothing.
    expect(eventsFromFrame(ROLE_OPENER)).toEqual([]);
  });

  it("reads the finish reason", () => {
    expect(eventsFromFrame(FINISH)).toEqual([{ kind: "finish", reason: "stop" }]);
  });

  it("reads usage and keeps cost_usdc a string", () => {
    const [event] = eventsFromFrame(USAGE);
    expect(event).toEqual({
      kind: "usage",
      usage: { prompt_tokens: 10, completion_tokens: 4, total_tokens: 14 },
      costUsdc: "0.000105",
      providerId: "00000000-0000-0000-0000-000000000000",
    });
    // A decimal parsed as a number is how a billing UI starts lying. It stays a string all
    // the way to the app's single USDC parser.
    expect(typeof (event as { costUsdc: string }).costUsdc).toBe("string");
  });

  it("reads the error frame, which carries no choices at all", () => {
    // This shape has no `object` and no `choices`. A parser that reached for choices first
    // would read it as an empty chunk and silently show nothing.
    expect(eventsFromFrame(ERROR)).toEqual([
      { kind: "error", message: "The node failed to complete the request." },
    ]);
  });

  it("carries both a delta and a finish reason when one frame has both", () => {
    // The backend does not currently emit this, but OpenAI's format allows it and assuming
    // one-event-per-frame would drop the finish reason the day it does.
    const both = {
      choices: [{ index: 0, delta: { content: "x" }, finish_reason: "length" }],
    };
    expect(eventsFromFrame(both)).toEqual([
      { kind: "delta", content: "x" },
      { kind: "finish", reason: "length" },
    ]);
  });

  it.each([
    ["null", null],
    ["a string", "nope"],
    ["an array", [1, 2]],
    ["choices not an array", { choices: "abc" }],
    ["choices[0] not an object", { choices: ["abc"] }],
    ["delta not an object", { choices: [{ delta: "abc" }] }],
    ["content not a string", { choices: [{ delta: { content: 42 } }] }],
    ["usage not an object", { usage: "abc" }],
    ["usage counts not numbers", { usage: { prompt_tokens: "a", completion_tokens: "b" } }],
    ["usage counts negative", { usage: { prompt_tokens: -1, completion_tokens: -2 } }],
  ])("drops %s rather than passing it on", (_label, payload) => {
    expect(eventsFromFrame(payload)).toEqual([]);
  });
});

describe("stream reading", () => {
  it("yields deltas progressively, and [DONE] ends it", async () => {
    const events = await collect(
      chatStreamEvents(
        streamOf(
          frame(ROLE_OPENER),
          frame(content("Hel")),
          frame(content("lo")),
          frame(FINISH),
          frame(USAGE),
          "data: [DONE]\n\n",
        ),
      ),
    );

    expect(events.map((e) => e.kind)).toEqual(["delta", "delta", "finish", "usage"]);
    expect(events.filter((e) => e.kind === "delta").map((e) => e.content)).toEqual(["Hel", "lo"]);
  });

  it("stops at [DONE] and ignores anything after it", async () => {
    const events = await collect(
      chatStreamEvents(streamOf(frame(content("a")), "data: [DONE]\n\n", frame(content("late")))),
    );
    expect(events).toEqual([{ kind: "delta", content: "a" }]);
  });

  it("reassembles a frame split across reads", async () => {
    // The network decides where reads land, not the sender. A parser that assumed one read
    // per frame would corrupt every long reply.
    const whole = frame(content("hello"));
    const events = await collect(
      chatStreamEvents(streamOf(whole.slice(0, 9), whole.slice(9, 20), whole.slice(20))),
    );
    expect(events).toEqual([{ kind: "delta", content: "hello" }]);
  });

  it("keeps a multi-byte character whole across a read boundary", async () => {
    // "é" is two bytes; splitting between them and decoding each read independently
    // produces replacement characters.
    const text = frame(content("café"));
    const bytes = new TextEncoder().encode(text);
    const cut = bytes.indexOf(0xc3) + 1; // mid-character
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, cut));
        controller.enqueue(bytes.slice(cut));
        controller.close();
      },
    });
    const events = await collect(chatStreamEvents(stream));
    expect(events).toEqual([{ kind: "delta", content: "café" }]);
  });

  it("survives a malformed frame mid-stream", async () => {
    // One bad frame must not discard a reply the developer is already reading — and has
    // already been billed for.
    const events = await collect(
      chatStreamEvents(
        streamOf(
          frame(content("a")),
          "data: {not json\n\n",
          frame(content("b")),
          "data: [DONE]\n\n",
        ),
      ),
    );
    expect(events).toEqual([
      { kind: "delta", content: "a" },
      { kind: "delta", content: "b" },
    ]);
  });

  it("joins multiple data: lines in one frame, per the SSE spec", async () => {
    const events = await collect(
      chatStreamEvents(streamOf('data: {"choices":[{"delta":\ndata: {"content":"x"}}]}\n\n')),
    );
    expect(events).toEqual([{ kind: "delta", content: "x" }]);
  });

  it("closes the body when the consumer stops reading", async () => {
    // Abandoning the generator has to close the connection: a client disconnect is what
    // tells the coordinator to stop the node. A parser that merely stopped reading would
    // leave a GPU running.
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(frame(content("a"))));
      },
      cancel() {
        cancelled = true;
      },
    });

    const gen = sseFrames(stream);
    await gen.next();
    await gen.return(undefined);

    expect(cancelled).toBe(true);
  });
});
