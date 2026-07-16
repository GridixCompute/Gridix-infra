/**
 * ⚠️ MOCK INFERENCE — SYNTHETIC TEXT, NO MODEL, NO GPU, NO CHARGE.
 *
 * The backend has no `/v1/*` endpoints, so this stands in for them well enough to build and
 * look at the playground UI. It is not a simulation of the product: nothing here reasons,
 * bills, or reaches a provider. The numbers it reports are arithmetic on a made-up rate card.
 *
 * It is deliberately obvious rather than convincing — see `isMockInference` and the banner
 * the playground renders. A mock that looks real is how a demo gets mistaken for a product.
 *
 * Delete this together with `types.ts` when `/v1/*` lands.
 */

import type {
  ChatRequest,
  ChatStreamEvent,
  ImageRequest,
  ImageResponse,
  ImageSize,
  InferenceModel,
} from "./types";

/** Mock is ON unless someone explicitly points the app at a real inference backend. */
export const isMockInference = process.env.NEXT_PUBLIC_INFERENCE_MOCK !== "false";

/** A plausible rate card, invented. Real prices must come from GET /v1/models. */
export const MOCK_MODELS: InferenceModel[] = [
  {
    id: "gridix/llama-3.1-8b-instruct",
    name: "Llama 3.1 8B Instruct",
    kind: "chat",
    available: true,
    pricePer1kInput: 60,
    pricePer1kOutput: 120,
    contextWindow: 131_072,
  },
  {
    id: "gridix/llama-3.1-70b-instruct",
    name: "Llama 3.1 70B Instruct",
    kind: "chat",
    available: true,
    pricePer1kInput: 520,
    pricePer1kOutput: 1_040,
    contextWindow: 131_072,
  },
  {
    id: "gridix/mistral-7b-instruct",
    name: "Mistral 7B Instruct",
    kind: "chat",
    available: false, // exercises the "no provider serving this" path
    pricePer1kInput: 45,
    pricePer1kOutput: 90,
    contextWindow: 32_768,
  },
  {
    id: "gridix/sdxl-turbo",
    name: "SDXL Turbo",
    kind: "image",
    available: true,
    pricePerImage: 4_000,
  },
];

const LOREM = [
  "This reply is synthetic.",
  "There is no model behind it and no GPU ran to produce it —",
  "the playground is streaming canned tokens so the interface can be built and reviewed",
  "before the inference backend exists.",
  "Token timing, cost accounting, and the stop control are all real code paths;",
  "only the words are fake.",
  "When /v1/chat/completions lands, this mock is deleted and the same client talks to it.",
];

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/** Crude token estimate. The real count comes from the node's tokenizer. */
export function estimateTokens(text: string): number {
  return Math.max(1, Math.ceil(text.length / 4));
}

/**
 * Stream a fake completion. Mirrors the real client's contract exactly — same events, same
 * abort semantics — so swapping in the real one changes nothing above this line.
 */
export async function* mockChatStream(
  req: ChatRequest,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  await sleep(220); // time-to-first-token

  const model = MOCK_MODELS.find((m) => m.id === req.model);
  const words = LOREM.join(" ").split(" ");
  let completion = "";

  for (const word of words) {
    if (signal?.aborted) break;
    const chunk = `${word} `;
    completion += chunk;
    yield { type: "delta", content: chunk };
    await sleep(28 + Math.random() * 34);
  }

  const promptText = req.messages.map((m) => m.content).join(" ");
  const promptTokens = estimateTokens(promptText);
  const completionTokens = estimateTokens(completion);
  const inRate = model?.pricePer1kInput ?? 0;
  const outRate = model?.pricePer1kOutput ?? 0;

  yield {
    type: "done",
    finishReason: signal?.aborted ? null : "stop",
    usage: {
      prompt_tokens: promptTokens,
      completion_tokens: completionTokens,
      cost_micro_usdc: Math.round(
        (promptTokens / 1000) * inRate + (completionTokens / 1000) * outRate,
      ),
    },
  };
}

export async function mockListModels(): Promise<InferenceModel[]> {
  await sleep(150);
  return MOCK_MODELS;
}

const SIZE_PX: Record<ImageSize, number> = { "512x512": 512, "768x768": 768, "1024x1024": 1024 };

/**
 * A placeholder "generation": an SVG that says so, in the requested size.
 *
 * Deliberately not a pretty picture. A mock image that looked like a real generation is a
 * screenshot away from being presented as product — so it renders its own disclaimer, plus
 * the prompt and seed it was asked for, which is what actually helps while building the
 * panel around it.
 */
function placeholderSvg(req: ImageRequest): string {
  // Every size we offer is square; a lookup keeps this total instead of parsing the label.
  const w = SIZE_PX[req.size];
  const h = w;
  const prompt = req.prompt.slice(0, 48).replace(/[<>&"]/g, "");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
  <rect width="${w}" height="${h}" fill="#111820"/>
  <rect x="8" y="8" width="${w - 16}" height="${h - 16}" fill="none" stroke="#ffab3d" stroke-width="2" stroke-dasharray="8 6"/>
  <text x="50%" y="42%" fill="#ffab3d" font-family="monospace" font-size="${Math.round(w / 18)}" font-weight="bold" text-anchor="middle">NO IMAGE WAS GENERATED</text>
  <text x="50%" y="52%" fill="#7e8c98" font-family="monospace" font-size="${Math.round(w / 32)}" text-anchor="middle">mock — no model, no GPU</text>
  <text x="50%" y="62%" fill="#aeb9c4" font-family="monospace" font-size="${Math.round(w / 38)}" text-anchor="middle">${prompt}</text>
  <text x="50%" y="70%" fill="#45525f" font-family="monospace" font-size="${Math.round(w / 44)}" text-anchor="middle">${req.size} · ${req.steps} steps · seed ${req.seed ?? "auto"}</text>
</svg>`;
  // btoa is latin1-only; the SVG is ASCII by construction (prompt is sliced/stripped above).
  return btoa(unescape(encodeURIComponent(svg)));
}

/** Mirrors the real client's contract: same shape in, same shape out, abortable. */
export async function mockGenerateImage(
  req: ImageRequest,
  signal?: AbortSignal,
): Promise<ImageResponse> {
  // Long enough that the progress state is a real state and not a flicker.
  for (let i = 0; i < 12; i++) {
    if (signal?.aborted) throw new DOMException("aborted", "AbortError");
    await sleep(90);
  }
  const model = MOCK_MODELS.find((m) => m.id === req.model);
  return {
    created: 0, // stamped by the caller; Date.now() here would make snapshots unstable
    data: [{ b64_json: placeholderSvg(req) }],
    usage: { cost_micro_usdc: model?.pricePerImage ?? 0 },
  };
}
