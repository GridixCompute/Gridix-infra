/**
 * The free tier's client: `/public/*`, not `/v1/*`.
 *
 * The playground talks to the free path exclusively. `/v1` is the paid product — it gates on
 * a balance, holds against it, and settles to the ledger — and a page anyone can open
 * without an account has no business reaching it. Keeping the two clients apart is what
 * makes that structural rather than a rule someone has to remember: there is no code path
 * from this module into the billed one.
 *
 * Chat is anonymous. Images require a wallet session, are counted five per wallet per day,
 * and are prompt-screened server-side — see `api/app/routes/public.py`. Nothing here decides
 * any of that; the server does, and this reports what it says.
 */

import { chatStreamEvents, type ChatStreamEvent } from "@/lib/inference/sse";

/**
 * The same-origin proxy, not the coordinator's origin.
 *
 * Two reasons, either sufficient: the CSP allows `connect-src 'self'` and the chain RPC, so
 * a direct call to the backend origin is blocked before it leaves the page; and the image
 * endpoints need the httpOnly session cookie, which browser JS cannot read and only a
 * server-side proxy can attach. `/api/public` forwards the session when there is one and
 * proxies anonymously when there is not — see its route for why `/api/gw` cannot be used.
 */
const BASE = "/api/public";

export type FreeModel = { id: string; free: boolean };

export type FreeModels = {
  chat: FreeModel[];
  images: FreeModel[];
  images_available: boolean;
};

export type ImageQuota = {
  limit: number;
  used: number;
  remaining: number;
  resets: string;
  available: boolean;
};

export class PublicApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "PublicApiError";
    this.status = status;
  }
}

/** Anything that never reached the server reads the same as a server that refused. */
async function send(path: string, init: RequestInit = {}): Promise<Response> {
  try {
    return await fetch(`${BASE}${path}`, { credentials: "include", ...init });
  } catch (e) {
    if ((e as Error)?.name === "AbortError") throw e;
    throw new PublicApiError(0, "Can't reach GRIDIX. Check your connection.");
  }
}

export async function fetchFreeModels(signal?: AbortSignal): Promise<FreeModels> {
  const res = await send("/models", { signal });
  if (!res.ok) throw new PublicApiError(res.status, "Couldn't load the free models.");
  return (await res.json()) as FreeModels;
}

/**
 * Stream a free chat completion. No account, no balance, no cost.
 *
 * The SSE parser is shared with the paid path because the server emits the same
 * `chat.completion.chunk` shape on both — one parser, one set of edge cases, one place where
 * a frame change breaks the build. The free stream simply never carries a `usage` event,
 * since there is nothing to bill.
 *
 * `signal` reaches `fetch`, so aborting really closes the connection — which is how the
 * coordinator learns to stop the node rather than generating for a caller who has gone.
 */
export async function* streamPublicChat(
  messages: { role: "system" | "user" | "assistant"; content: string }[],
  options: { maxTokens?: number; temperature?: number } = {},
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  const res = await send("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({
      messages,
      max_tokens: options.maxTokens ?? 512,
      temperature: options.temperature ?? 0.7,
    }),
    signal,
  });

  if (res.status === 429) {
    throw new PublicApiError(429, "You're sending messages very fast. Wait a moment.");
  }
  if (res.status === 503) {
    throw new PublicApiError(503, "The free model is offline right now. Try again shortly.");
  }
  if (!res.ok || !res.body) {
    throw new PublicApiError(res.status, "The model couldn't answer. Try again.");
  }

  yield* chatStreamEvents(res.body, signal);
}

/**
 * Today's image allowance for the signed-in wallet.
 *
 * 401 is not an error to surface — it is the ordinary state of a visitor who has not
 * connected a wallet, and the page shows an invitation rather than a failure. Returning null
 * keeps that distinction at the boundary instead of making every caller inspect a status.
 */
export async function fetchImageQuota(signal?: AbortSignal): Promise<ImageQuota | null> {
  const res = await send("/images/quota", { signal });
  if (res.status === 401 || res.status === 403) return null;
  if (!res.ok) throw new PublicApiError(res.status, "Couldn't read your image allowance.");
  return (await res.json()) as ImageQuota;
}

export type GeneratedImage = { url: string };

/**
 * Generate one free image. Requires a wallet session.
 *
 * The refusal messages are deliberately distinct, because they mean different things to the
 * person reading them: 401 means "connect a wallet", 400 means "that prompt was refused",
 * 429 means "you've used today's five". Collapsing them into "something went wrong" would
 * leave a visitor with no idea which of the three applies to them.
 */
export async function generatePublicImage(
  prompt: string,
  signal?: AbortSignal,
): Promise<GeneratedImage[]> {
  const res = await send("/images", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
    signal,
  });

  if (res.ok) {
    const body = (await res.json()) as { data?: GeneratedImage[] };
    return body.data ?? [];
  }

  const detail = await res
    .json()
    .then((b: { error?: { message?: string } }) => b?.error?.message)
    .catch(() => undefined);

  if (res.status === 401 || res.status === 403) {
    throw new PublicApiError(res.status, "Connect your wallet to generate images.");
  }
  if (res.status === 400) {
    throw new PublicApiError(400, detail ?? "That prompt was refused.");
  }
  if (res.status === 429) {
    throw new PublicApiError(429, detail ?? "You've used today's free images.");
  }
  throw new PublicApiError(res.status, detail ?? "Image generation isn't available yet.");
}
