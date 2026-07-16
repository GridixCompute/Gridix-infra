/**
 * Inference client (Sesi 4.2) — chat completions over SSE.
 *
 * The real path is written out in full even though nothing serves it yet: the mock and the
 * backend expose the *same* generator contract, so landing `/v1/chat/completions` is a flag
 * flip (`NEXT_PUBLIC_INFERENCE_MOCK=false`), not a rewrite. Everything above this module —
 * ChatPanel, cost display, the stop button — is already talking to the real shape.
 *
 * ⚠️ The request/response shapes come from `./types`, which is a GUESS (see its header). The
 * real endpoint may disagree; the compiler cannot warn you, because there is no generated
 * schema to check against.
 */

import { env } from "@/lib/config/env";
import { isMockInference, mockChatStream, mockListModels } from "./mock";
import type { ChatRequest, ChatStreamChunk, ChatStreamEvent, InferenceModel } from "./types";

/** Errors the playground must react to differently (Sesi 4.2). */
export type InferenceErrorKind =
  | "insufficient_balance" // 403 — top up
  | "node_timeout" // 504 — the provider took too long
  | "node_error" // 502 — the provider failed
  | "model_unavailable" // 404 — nobody is serving it
  | "rate_limited" // 429
  | "unauthorized" // 401
  | "network" // never reached the coordinator
  | "unknown";

export class InferenceError extends Error {
  readonly kind: InferenceErrorKind;
  constructor(kind: InferenceErrorKind, message: string) {
    super(message);
    this.name = "InferenceError";
    this.kind = kind;
  }
}

function kindFromStatus(status: number): InferenceErrorKind {
  switch (status) {
    case 401:
      return "unauthorized";
    case 403:
      return "insufficient_balance";
    case 404:
      return "model_unavailable";
    case 429:
      return "rate_limited";
    case 502:
      return "node_error";
    case 504:
      return "node_timeout";
    default:
      return "unknown";
  }
}

const MESSAGES: Record<InferenceErrorKind, string> = {
  insufficient_balance: "Not enough USDC to cover this request. Top up to continue.",
  node_timeout: "The provider running this model didn't respond in time. Try again.",
  node_error: "The provider running this model failed. Try again or pick another model.",
  model_unavailable: "No provider is serving this model right now.",
  rate_limited: "Too many requests. Wait a moment and try again.",
  unauthorized: "Your session expired. Sign in again.",
  network: "Can't reach GRIDIX. Check your connection.",
  unknown: "Inference failed. Try again.",
};

export function inferenceErrorMessage(err: unknown): string {
  return err instanceof InferenceError ? err.message : MESSAGES.unknown;
}

export async function listModels(signal?: AbortSignal): Promise<InferenceModel[]> {
  if (isMockInference) return mockListModels();

  const res = await fetch(`${env.apiUrl}/v1/models`, { signal, credentials: "include" });
  if (!res.ok) throw new InferenceError(kindFromStatus(res.status), MESSAGES[kindFromStatus(res.status)]);
  const body = (await res.json()) as { data: InferenceModel[] };
  return body.data;
}

/**
 * Stream a chat completion, yielding one event per token batch.
 *
 * Parses the SSE frames by hand rather than using EventSource, which is GET-only and cannot
 * send the request body. `signal` maps to the stop button: aborting mid-stream ends the
 * generator, and the tokens already yielded stay on screen and stay billable.
 */
export async function* streamChat(
  req: ChatRequest,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  if (isMockInference) {
    yield* mockChatStream(req, signal);
    return;
  }

  let res: Response;
  try {
    res = await fetch(`${env.apiUrl}/v1/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(req),
      credentials: "include",
      signal,
    });
  } catch (e) {
    if ((e as Error)?.name === "AbortError") return;
    throw new InferenceError("network", MESSAGES.network);
  }

  if (!res.ok || !res.body) {
    const kind = kindFromStatus(res.status);
    throw new InferenceError(kind, MESSAGES[kind]);
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let usage: ChatStreamChunk["usage"] = undefined;
  let finishReason: "stop" | "length" | null = null;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += value;

      // SSE frames are separated by a blank line; a frame may span several reads.
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        const line = frame.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        const payload = line.slice(5).trim();
        if (payload === "[DONE]") continue;

        let chunk: ChatStreamChunk;
        try {
          chunk = JSON.parse(payload) as ChatStreamChunk;
        } catch {
          continue; // a malformed frame must not kill a live stream
        }

        if (chunk.usage) usage = chunk.usage;
        const choice = chunk.choices?.[0];
        if (choice?.finish_reason) finishReason = choice.finish_reason;
        const content = choice?.delta?.content;
        if (content) yield { type: "delta", content };
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }

  yield { type: "done", usage: usage ?? null, finishReason };
}
