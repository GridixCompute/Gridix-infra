/**
 * ⚠️ HAND-WRITTEN, PROVISIONAL TYPES — NOT GENERATED, NOT A CONTRACT. DELETE ON ARRIVAL.
 *
 * Every other type the app uses comes from `@/lib/api/schema`, generated from the backend's
 * OpenAPI by `pnpm gen:types` and policed by the `openapi-drift` CI gate. These do not,
 * because the endpoints they describe (`/v1/models`, `/v1/chat/completions`,
 * `/v1/images/generations`) **DO NOT EXIST IN THE BACKEND**. There is nothing to generate
 * from. This file is a guess at an OpenAI-compatible shape so the playground UI can be built
 * and looked at before the backend is written.
 *
 * That is a deliberate, accepted trade: these types WILL drift, and the drift gate cannot
 * catch it — the gate only diffs what it can generate. When `/v1/*` lands:
 *
 *   1. Run `python api/scripts/dump_openapi.py && pnpm --dir frontend gen:types`.
 *   2. Delete this file and re-point `@/lib/inference/*` at the generated `schema.ts`.
 *   3. Expect the compiler to reject things. Fix them against the REAL schema, never by
 *      editing this file to agree with itself.
 *
 * Do not import these anywhere outside `src/lib/inference/` and `src/components/playground/`,
 * and do not add fields here to make a UI idea work — that is how a guess quietly becomes an
 * assumed contract.
 */

/** A model the network can serve. Priced per-token (chat) or per-image (image). */
export type InferenceModel = {
  id: string;
  /** Human label; the id is what the API takes. */
  name: string;
  kind: "chat" | "image";
  /** Whether providers are currently serving it. */
  available: boolean;
  /** Micro-USDC (6dp) per 1K input tokens. Chat models only. */
  pricePer1kInput?: number;
  /** Micro-USDC (6dp) per 1K output tokens. Chat models only. */
  pricePer1kOutput?: number;
  /** Micro-USDC (6dp) per generated image. Image models only. */
  pricePerImage?: number;
  contextWindow?: number;
};

export type ChatRole = "system" | "user" | "assistant";

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

/** Knobs the settings panel drives (Sesi 4.4). `seed` ties to backend canary determinism. */
export type ChatParams = {
  temperature: number;
  maxTokens: number;
  topP: number;
  /** null = let the node choose; a number pins determinism. */
  seed: number | null;
};

export type ChatRequest = {
  model: string;
  messages: ChatMessage[];
  stream: true;
  temperature?: number;
  max_tokens?: number;
  top_p?: number;
  seed?: number | null;
};

/** One SSE `data:` frame of a streamed completion (OpenAI-compatible shape). */
export type ChatStreamChunk = {
  id: string;
  object: "chat.completion.chunk";
  model: string;
  choices: {
    index: number;
    delta: { role?: ChatRole; content?: string };
    finish_reason: "stop" | "length" | null;
  }[];
  /** GRIDIX extension: usage/cost on the final frame so the UI can bill honestly. */
  usage?: ChatUsage;
};

export type ChatUsage = {
  prompt_tokens: number;
  completion_tokens: number;
  /** Micro-USDC (6dp) actually charged for this completion. */
  cost_micro_usdc: number;
};

/** What the stream yields to the UI, one event at a time. */
export type ChatStreamEvent =
  | { type: "delta"; content: string }
  | { type: "done"; usage: ChatUsage | null; finishReason: "stop" | "length" | null };
