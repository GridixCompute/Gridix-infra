/**
 * Reading the `/v1/chat/completions` SSE stream.
 *
 * ⚠️ THE FRAME SHAPE IS NOT IN THE GENERATED SCHEMA, and that is the whole reason this file
 * is written the way it is. The backend declares the streamed response as
 * `"text/event-stream": {"schema": {"type": "string"}}` — an opaque string — so
 * `pnpm gen:types` has nothing to generate and the `openapi-drift` gate cannot police what
 * arrives here. The only typed thing on the wire is `ChatUsage`, which is a real component.
 *
 * This is exactly the hole that produced the bug #34 cleaned up: a hand-written guess at a
 * chunk shape, agreed with by a hand-written mock, wrong against the backend for months
 * without one failing test. So this module does NOT declare "the contract" and cast to it.
 * It narrows at RUNTIME, field by field, and anything it cannot recognise it drops rather
 * than passes on as though it were understood. A frame that changes shape produces a missing
 * event here, not a confidently wrong object three layers up.
 *
 * The shapes below are read off the emission sites in `api/app/streaming_chat.py`, which is
 * the only authority that exists:
 *
 *   role opener   {..., "choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}
 *   content       {..., "choices":[{"index":0,"delta":{"content":"..."},"finish_reason":null}]}
 *   finish        {..., "choices":[{"index":0,"delta":{},"finish_reason":"stop"|"length"}]}
 *   usage/cost    {..., "choices":[], "usage":{...}, "cost_usdc":"0.000105", "provider_id":"..."}
 *   failure       {"error":{"message":"..."}}
 *   terminator    [DONE]
 *
 * The proper fix is a declared component schema on the backend so this can be generated and
 * gated; until then, defensive parsing plus tests pinned to those emission sites is the
 * honest substitute. Noted as a follow-up rather than silently tolerated.
 */

import type { components } from "@/lib/api/schema";

/** The one piece of a streamed frame that IS generated. */
export type ChatUsage = components["schemas"]["ChatUsage"];

/**
 * What the UI consumes. Deliberately narrower than the wire: the panel should never have to
 * reach into `choices[0].delta` itself, or it inherits every shape assumption this file
 * exists to contain.
 */
export type ChatStreamEvent =
  | { kind: "delta"; content: string }
  | { kind: "finish"; reason: string | null }
  | { kind: "usage"; usage: ChatUsage; costUsdc: string; providerId: string }
  | { kind: "error"; message: string };

const DONE = "[DONE]";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asNonNegativeInt(value: unknown): number | null {
  // `typeof true === "boolean"`, so bools are already excluded; NaN and Infinity are not.
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return null;
  return Math.floor(value);
}

/** A `ChatUsage` only if every field is really there and really a count. */
function readUsage(raw: unknown): ChatUsage | null {
  if (!isRecord(raw)) return null;
  const prompt = asNonNegativeInt(raw.prompt_tokens);
  const completion = asNonNegativeInt(raw.completion_tokens);
  if (prompt === null || completion === null) return null;
  const total = asNonNegativeInt(raw.total_tokens);
  return {
    prompt_tokens: prompt,
    completion_tokens: completion,
    total_tokens: total ?? prompt + completion,
  };
}

/**
 * Turn one decoded `data:` payload into the events it represents.
 *
 * Returns a list because a single frame may legitimately carry both a delta and a finish
 * reason. The backend does not currently emit such a frame, but OpenAI's own format allows
 * it and tolerating it costs nothing — whereas assuming one-event-per-frame would silently
 * drop the finish reason the day it does.
 */
export function eventsFromFrame(payload: unknown): ChatStreamEvent[] {
  if (!isRecord(payload)) return [];

  // Failure first: this frame carries no `object` or `choices` at all, so anything that
  // looked for those first would read it as an empty chunk and show nothing.
  if (isRecord(payload.error)) {
    const message = payload.error.message;
    return [
      { kind: "error", message: typeof message === "string" ? message : "Inference failed." },
    ];
  }

  const events: ChatStreamEvent[] = [];

  const choices = payload.choices;
  const first = Array.isArray(choices) && isRecord(choices[0]) ? choices[0] : null;
  if (first) {
    const delta = isRecord(first.delta) ? first.delta : null;
    const content = delta?.content;
    // The role opener carries `{role: "assistant"}` and no content — nothing to render, and
    // an empty string would add a pointless re-render per stream.
    if (typeof content === "string" && content !== "") {
      events.push({ kind: "delta", content });
    }
    const reason = first.finish_reason;
    if (typeof reason === "string" && reason !== "") {
      events.push({ kind: "finish", reason });
    }
  }

  // Usage rides its own frame, with `choices: []`. `cost_usdc` is a decimal STRING (a
  // serialised Decimal), never a number — parsing it as one is how a billing UI starts
  // lying, so it is carried as a string and converted by the app's single USDC parser.
  const usage = readUsage(payload.usage);
  if (usage) {
    const cost = payload.cost_usdc;
    const provider = payload.provider_id;
    events.push({
      kind: "usage",
      usage,
      costUsdc: typeof cost === "string" ? cost : "0",
      providerId: typeof provider === "string" ? provider : "",
    });
  }

  return events;
}

/**
 * Split a byte stream into SSE `data:` payloads, yielding each as text.
 *
 * Frames are separated by a blank line and a frame may straddle reads, so the tail is
 * buffered rather than parsed. Multiple `data:` lines in one frame are joined with newlines,
 * per the SSE spec — the backend sends one line today, and honouring the spec costs nothing
 * against the day it wraps a long payload.
 *
 * Cancelling the reader in the `finally` is load-bearing: abandoning this generator has to
 * close the underlying connection, because a client disconnect is what tells the coordinator
 * to stop the node. A parser that merely stopped reading would leave a GPU running.
 */
export async function* sseFrames(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<string> {
  // Decoded by hand rather than through `TextDecoderStream`: `pipeThrough` types the
  // decoder's writable side as BufferSource, which does not line up with
  // ReadableStream<Uint8Array> without a cast — and a cast on the one boundary where bytes
  // become text is exactly where a cast should not be. `{stream: true}` keeps a multi-byte
  // character whole across reads.
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) return;
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        const data = frame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice("data:".length).trim())
          .join("\n");
        if (data !== "") yield data;
      }
    }
  } finally {
    // Best-effort: the reader may already be errored by an abort, which is not a failure.
    reader.cancel().catch(() => {});
  }
}

/**
 * The full read: byte stream in, `ChatStreamEvent`s out, ending at `[DONE]`.
 *
 * A frame that will not parse as JSON is skipped rather than fatal. One malformed frame must
 * not discard a reply the developer is already reading — and has already been billed for.
 */
export async function* chatStreamEvents(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  for await (const data of sseFrames(body, signal)) {
    if (data === DONE) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(data);
    } catch {
      continue;
    }
    for (const event of eventsFromFrame(parsed)) yield event;
  }
}
