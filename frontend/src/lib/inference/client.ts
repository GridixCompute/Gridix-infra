/**
 * Inference client for `/v1/models`, `/v1/chat/completions` and `/v1/images/generations`.
 *
 * Types come from `./contract`, which aliases the generated schema. Nothing here restates a
 * wire shape.
 *
 * Chat comes in two shapes, matching the backend: `createChatCompletion` for one complete
 * reply, and `streamChatCompletion` for SSE. The streamed one is real now — the relay
 * forwards frames as the node produces them — where the parser deleted in #34 decoded a
 * `chat.completion.chunk` the backend had never emitted. Frame parsing lives in `./sse`,
 * which explains why it narrows at runtime instead of casting.
 */

import { env } from "@/lib/config/env";
import {
  isMockInference,
  mockChatCompletion,
  mockChatStream,
  mockGenerateImage,
  mockListModels,
} from "./mock";
import { chatStreamEvents, type ChatStreamEvent } from "./sse";
import type {
  ChatCompletionRequest,
  ChatCompletionResponse,
  ImageGenerationRequest,
  ImageGenerationResponse,
  ModelInfo,
  ModelsResponse,
} from "./contract";

export type { ChatStreamEvent } from "./sse";

/**
 * Errors the playground must react to differently.
 *
 * Mapped from the statuses the backend actually returns — verified against
 * `api/app/routes/inference.py`, not assumed. The previous mapping had two live bugs: it read
 * **403** as "insufficient balance" (the backend uses **402**; 403 is a credentials problem)
 * and had no case for **503**, the code returned when a model exists but nothing is serving
 * it. Both would have shown the wrong message the first time a real request failed.
 */
export type InferenceErrorKind =
  | "insufficient_balance" // 402 — top up
  | "unauthorized" // 401 — not signed in
  | "forbidden" // 403 — signed in, wrong credentials for this route
  | "unknown_model" // 404 — the catalogue has no such model
  | "rate_limited" // 429
  | "not_implemented" // 501 — e.g. stream=true, confidential_tee
  | "node_error" // 502 — the provider failed
  | "no_node" // 503 — the model exists, nothing is serving it
  | "node_timeout" // 504 — the provider took too long
  | "network" // never reached the coordinator
  | "unknown";

export class InferenceError extends Error {
  readonly kind: InferenceErrorKind;
  readonly status?: number;
  constructor(kind: InferenceErrorKind, message: string, status?: number) {
    super(message);
    this.name = "InferenceError";
    this.kind = kind;
    this.status = status;
  }
}

function kindFromStatus(status: number): InferenceErrorKind {
  switch (status) {
    case 401:
      return "unauthorized";
    case 402:
      return "insufficient_balance";
    case 403:
      return "forbidden";
    case 404:
      return "unknown_model";
    case 429:
      return "rate_limited";
    case 501:
      return "not_implemented";
    case 502:
      return "node_error";
    case 503:
      return "no_node";
    case 504:
      return "node_timeout";
    default:
      return "unknown";
  }
}

const MESSAGES: Record<InferenceErrorKind, string> = {
  insufficient_balance: "Not enough USDC to cover this request. Top up to continue.",
  unauthorized: "Your session expired. Sign in again.",
  forbidden: "This account isn't allowed to run inference.",
  unknown_model: "GRIDIX doesn't serve that model.",
  rate_limited: "Too many requests. Wait a moment and try again.",
  not_implemented: "The network can't serve this request yet.",
  node_error: "The provider running this model failed. Try again or pick another model.",
  no_node: "No provider is serving this model right now.",
  node_timeout: "The provider running this model didn't respond in time. Try again.",
  network: "Can't reach GRIDIX. Check your connection.",
  unknown: "Inference failed. Try again.",
};

export function inferenceErrorMessage(err: unknown): string {
  return err instanceof InferenceError ? err.message : MESSAGES.unknown;
}

function failed(status: number): InferenceError {
  const kind = kindFromStatus(status);
  return new InferenceError(kind, MESSAGES[kind], status);
}

/** An aborted request is the caller's own doing — rethrow it untouched, never as a failure. */
async function send(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (e) {
    if ((e as Error)?.name === "AbortError") throw e;
    throw new InferenceError("network", MESSAGES.network);
  }
}

export async function listModels(signal?: AbortSignal): Promise<ModelInfo[]> {
  if (isMockInference) return mockListModels();

  const res = await send(`${env.apiUrl}/v1/models`, { signal, credentials: "include" });
  if (!res.ok) throw failed(res.status);
  // `{models: [...]}`, not `{data: [...]}` — the hand-written types guessed the OpenAI
  // envelope here and the backend does not use it on this route.
  const body = (await res.json()) as ModelsResponse;
  return body.models;
}

/**
 * Stream one chat completion, yielding events as the node produces tokens.
 *
 * ⚠️ `signal` MUST reach `fetch`, and the caller aborting it is the only thing that stops
 * the work. The coordinator settles the hold and tells the node to stop generating when its
 * client disconnects — a UI that merely hid the output would leave a GPU running to the end
 * of its token budget and settle the hold for tokens nobody ever saw. Aborting the fetch is
 * what closes the TCP connection, which is what the whole cancel chain hangs off:
 *
 *   abort() -> connection closes -> coordinator's stream body is cancelled
 *           -> relay sends {"type":"cancel"} -> node cancels -> Ollama stops
 *
 * The `finally` matters for the same reason: a caller that stops iterating without aborting
 * would otherwise leave the response body open. Cancelling the reader closes it.
 */
export async function* streamChatCompletion(
  req: ChatCompletionRequest,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  if (isMockInference) {
    yield* mockChatStream(req, signal);
    return;
  }

  const res = await send(`${env.apiUrl}/v1/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ ...req, stream: true }),
    credentials: "include",
    signal,
  });

  // A failure before the stream opens is still a normal JSON error response, so the status
  // mapping applies unchanged. Once bytes are flowing the backend reports failure as an
  // `error` event instead, because the status line is long committed by then.
  if (!res.ok) throw failed(res.status);
  if (!res.body) throw new InferenceError("network", MESSAGES.network);

  yield* chatStreamEvents(res.body, signal);
}

/**
 * Run one chat completion and return the whole reply.
 *
 * Kept beside the streamed path rather than replaced by it: `stream=false` is what the code
 * snippets show and what a developer integrating server-side will send, so it stays a
 * first-class path. `stream` is forced false here for the same reason it is forced true
 * above — the shape of the reply this function returns depends on it.
 */
export async function createChatCompletion(
  req: ChatCompletionRequest,
  signal?: AbortSignal,
): Promise<ChatCompletionResponse> {
  if (isMockInference) return mockChatCompletion(req, signal);

  const res = await send(`${env.apiUrl}/v1/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...req, stream: false }),
    credentials: "include",
    signal,
  });
  if (!res.ok) throw failed(res.status);
  return (await res.json()) as ChatCompletionResponse;
}

/**
 * Generate one image.
 *
 * Unary for the same reason chat now is, plus a real one: there is no partial image to show,
 * so the panel renders a progress state and this resolves once.
 */
export async function generateImage(
  req: ImageGenerationRequest,
  signal?: AbortSignal,
): Promise<ImageGenerationResponse> {
  if (isMockInference) return mockGenerateImage(req, signal);

  const res = await send(`${env.apiUrl}/v1/images/generations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
    credentials: "include",
    signal,
  });
  if (!res.ok) throw failed(res.status);
  return (await res.json()) as ImageGenerationResponse;
}
