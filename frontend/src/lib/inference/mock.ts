/**
 * ⚠️ MOCK INFERENCE — SYNTHETIC TEXT, NO MODEL, NO GPU, NO CHARGE.
 *
 * Stands in for `/v1/*` so the playground can be built and looked at without a coordinator,
 * a node or a funded balance. It is not a simulation of the product: nothing here reasons,
 * bills, or reaches a provider.
 *
 * It is deliberately obvious rather than convincing — see `isMockInference` and the banner
 * the playground renders. A mock that looks real is how a demo gets mistaken for a product.
 *
 * Every shape below is the GENERATED type from `./contract`, so the mock cannot drift from
 * the backend without the compiler saying so. That is the whole discipline: the reason the
 * playground could run green on invented shapes for so long is that the mock agreed with the
 * guess instead of with the API. Typing the mock against the real contract is what makes
 * `NEXT_PUBLIC_INFERENCE_MOCK=false` a flag flip rather than a rewrite.
 */

import type {
  ChatCompletionRequest,
  ChatCompletionResponse,
  ImageGenerationRequest,
  ImageGenerationResponse,
  ModelInfo,
} from "./contract";
import { priceToBase } from "./pricing";
import type { ChatStreamEvent } from "./sse";
import { estimateTokens } from "./tokens";

/** Mock is ON unless someone explicitly points the app at a real inference backend. */
export const isMockInference = process.env.NEXT_PUBLIC_INFERENCE_MOCK !== "false";

/**
 * A stand-in catalogue.
 *
 * Ids and prices mirror `api/app/catalog.py` — same model ids, same decimal-USDC-per-1M-token
 * strings — so the mock exercises the same parsing and the same order of magnitude as the
 * real rate card. The previous mock invented both (`gridix/…` ids, integer micro-USDC per 1K)
 * and so proved nothing about the code that would run against the API.
 */
export const MOCK_MODELS: ModelInfo[] = [
  {
    id: "llama-3.1-8b",
    modality: "chat",
    available: true,
    nodes: 3,
    input_usdc_per_mtok: "0.05",
    output_usdc_per_mtok: "0.08",
    usdc_per_image: "0",
    context_window: 128_000,
  },
  {
    id: "llama-3.1-70b",
    modality: "chat",
    available: true,
    nodes: 1,
    input_usdc_per_mtok: "0.40",
    output_usdc_per_mtok: "0.80",
    usdc_per_image: "0",
    context_window: 128_000,
  },
  {
    id: "qwen-2.5-coder-32b",
    modality: "chat",
    available: false, // exercises the "no provider serving this" path
    nodes: 0,
    input_usdc_per_mtok: "0.18",
    output_usdc_per_mtok: "0.30",
    usdc_per_image: "0",
    context_window: 32_768,
  },
  {
    id: "sdxl-turbo",
    modality: "image",
    available: true,
    nodes: 2,
    input_usdc_per_mtok: "0",
    output_usdc_per_mtok: "0",
    usdc_per_image: "0.01",
    context_window: 0,
  },
];

const LOREM = [
  "This reply is synthetic.",
  "There is no model behind it and no GPU ran to produce it —",
  "the playground is answering from a canned string so the interface can be built and",
  "reviewed without a live network.",
  "Cost accounting, the balance gate and the cancel control are all real code paths;",
  "only the words are fake.",
  "Set NEXT_PUBLIC_INFERENCE_MOCK=false and the same client calls the real endpoint.",
].join(" ");

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/** Reject like a cancelled `fetch` does, so callers exercise their real abort branch. */
function aborted(): DOMException {
  return new DOMException("aborted", "AbortError");
}

async function wait(ms: number, signal?: AbortSignal): Promise<void> {
  const step = 30;
  for (let waited = 0; waited < ms; waited += step) {
    if (signal?.aborted) throw aborted();
    await sleep(step);
  }
  if (signal?.aborted) throw aborted();
}

function priceOf(models: ModelInfo[], id: string): ModelInfo | undefined {
  return models.find((m) => m.id === id);
}

/**
 * Cost in decimal USDC, as the backend reports it: a 6-decimal string.
 *
 * Six places is not cosmetic — it is USDC's resolution, and it is what the app's parser
 * accepts. A mock that emitted full float precision would produce a `cost_usdc` the real
 * backend never sends and the real parser would reject.
 */
function costUsdc(microUnits: bigint): string {
  const whole = microUnits / 1_000_000n;
  const frac = (microUnits % 1_000_000n).toString().padStart(6, "0");
  return `${whole}.${frac}`;
}

/** Mirrors the real client: one request, one complete reply. No streaming — see client.ts. */
export async function mockChatCompletion(
  req: ChatCompletionRequest,
  signal?: AbortSignal,
): Promise<ChatCompletionResponse> {
  // Long enough that "generating" is a real state and not a flicker.
  await wait(900, signal);

  const model = priceOf(MOCK_MODELS, req.model);
  const promptTokens = estimateTokens(req.messages.map((m) => m.content).join(" "));
  const completionTokens = estimateTokens(LOREM);

  // Parsed with the app's own USDC parser, not Number(): the mock must produce a `cost_usdc`
  // the real parser accepts, and a float round-trip is how it would eventually not.
  const inRate = priceToBase(model?.input_usdc_per_mtok ?? "0") ?? 0n;
  const outRate = priceToBase(model?.output_usdc_per_mtok ?? "0") ?? 0n;
  const micro = (BigInt(promptTokens) * inRate + BigInt(completionTokens) * outRate) / 1_000_000n;

  return {
    id: "chatcmpl-mock",
    object: "chat.completion",
    created: 0, // stamped by the caller; Date.now() here would make snapshots unstable
    model: req.model,
    choices: [{ index: 0, message: { role: "assistant", content: LOREM }, finish_reason: "stop" }],
    usage: {
      prompt_tokens: promptTokens,
      completion_tokens: completionTokens,
      total_tokens: promptTokens + completionTokens,
    },
    cost_usdc: costUsdc(micro),
    provider_id: "00000000-0000-0000-0000-000000000000",
  };
}

/**
 * Mirrors the real streamed client: deltas as they are "produced", then finish, then usage.
 *
 * Typed against the same `ChatStreamEvent` the SSE parser produces, so the mock cannot drift
 * from what the real path yields without the compiler saying so. That is the discipline #34
 * was about: the previous mock agreed with a hand-written guess instead of with the API, and
 * hid a broken client for months.
 *
 * The abort check is inside the loop rather than only at the top, because cancelling
 * mid-generation is the case the panel has to get right. When mock mode is off, the same
 * abort tears down a real TCP connection and stops a real GPU.
 */
export async function* mockChatStream(
  req: ChatCompletionRequest,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  await wait(220, signal); // time-to-first-token

  const model = priceOf(MOCK_MODELS, req.model);
  const words = LOREM.split(" ");
  let emitted = "";

  for (const word of words) {
    if (signal?.aborted) throw aborted();
    const piece = `${word} `;
    emitted += piece;
    yield { kind: "delta", content: piece };
    await wait(45, signal);
  }

  const promptTokens = estimateTokens(req.messages.map((m) => m.content).join(" "));
  const completionTokens = estimateTokens(emitted);
  const inRate = priceToBase(model?.input_usdc_per_mtok ?? "0") ?? 0n;
  const outRate = priceToBase(model?.output_usdc_per_mtok ?? "0") ?? 0n;
  const micro = (BigInt(promptTokens) * inRate + BigInt(completionTokens) * outRate) / 1_000_000n;

  yield { kind: "finish", reason: "stop" };
  yield {
    kind: "usage",
    usage: {
      prompt_tokens: promptTokens,
      completion_tokens: completionTokens,
      total_tokens: promptTokens + completionTokens,
    },
    costUsdc: costUsdc(micro),
    providerId: "00000000-0000-0000-0000-000000000000",
  };
}

export async function mockListModels(): Promise<ModelInfo[]> {
  await sleep(150);
  return MOCK_MODELS;
}

/**
 * A placeholder "generation": an SVG that says so, delivered as a `data:` URL.
 *
 * Deliberately not a pretty picture. A mock image that looked like a real generation is a
 * screenshot away from being presented as product — so it renders its own disclaimer plus the
 * prompt and seed it was asked for, which is what actually helps while building the panel.
 *
 * A `data:` URL because `GeneratedImage` carries a **url**, not `b64_json`: nodes return a
 * reference to a stored artefact and never inline bytes. The old mock returned `b64_json`,
 * a field the backend deliberately does not have, and the panel had grown base64 sniffing to
 * consume it. Both are gone.
 */
function placeholderUrl(req: ImageGenerationRequest): string {
  const size = 768;
  const prompt = req.prompt.slice(0, 48).replace(/[<>&"]/g, "");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <rect width="${size}" height="${size}" fill="#111820"/>
  <rect x="8" y="8" width="${size - 16}" height="${size - 16}" fill="none" stroke="#ffab3d" stroke-width="2" stroke-dasharray="8 6"/>
  <text x="50%" y="42%" fill="#ffab3d" font-family="monospace" font-size="${Math.round(size / 18)}" font-weight="bold" text-anchor="middle">NO IMAGE WAS GENERATED</text>
  <text x="50%" y="52%" fill="#7e8c98" font-family="monospace" font-size="${Math.round(size / 32)}" text-anchor="middle">mock — no model, no GPU</text>
  <text x="50%" y="62%" fill="#aeb9c4" font-family="monospace" font-size="${Math.round(size / 38)}" text-anchor="middle">${prompt}</text>
  <text x="50%" y="70%" fill="#45525f" font-family="monospace" font-size="${Math.round(size / 44)}" text-anchor="middle">seed ${req.seed ?? "auto"}</text>
</svg>`;
  // encodeURIComponent keeps this valid for any prompt bytes without a latin1 btoa round-trip.
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

/** Mirrors the real client's contract: same shape in, same shape out, abortable. */
export async function mockGenerateImage(
  req: ImageGenerationRequest,
  signal?: AbortSignal,
): Promise<ImageGenerationResponse> {
  await wait(1080, signal);

  const model = priceOf(MOCK_MODELS, req.model);
  const perImage = priceToBase(model?.usdc_per_image ?? "0") ?? 0n;

  return {
    created: 0, // stamped by the caller; see mockChatCompletion
    data: [{ url: placeholderUrl(req) }],
    model: req.model,
    cost_usdc: costUsdc(perImage * BigInt(req.n)),
    provider_id: "00000000-0000-0000-0000-000000000000",
  };
}
