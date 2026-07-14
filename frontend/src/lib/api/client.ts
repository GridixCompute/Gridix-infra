/**
 * Central API client (Sesi 1.4). Single place that:
 *  - resolves the base URL from validated env,
 *  - injects the API key (server-side only — see note below),
 *  - enforces a timeout via AbortController,
 *  - retries lightly, but ONLY idempotent GETs,
 *  - returns generated OpenAPI types (never hand-written).
 *
 * Auth note: the browser must not read the API key (Sesi 4.2 — httpOnly cookie).
 * So on the client we call our own Next route handlers under `/api/*`, which
 * attach the key server-side. `apiKey` here is for that server context.
 */
import type { paths } from "./schema";
import { ApiError, toApiError, toNetworkError } from "./errors";

export type Paths = paths;

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  /** Overrides the default per-request timeout (ms). */
  timeoutMs?: number;
  /** Extra headers (e.g. Content-Type for uploads). */
  headers?: Record<string, string>;
  /** Caller-provided abort signal, composed with the timeout. */
  signal?: AbortSignal;
  /** Number of retries for idempotent GETs on transient failure. */
  retries?: number;
};

const DEFAULT_TIMEOUT_MS = 15_000;

export type ApiClientConfig = {
  baseUrl: string;
  /** Attached as `X-API-Key`. Server-side only. */
  apiKey?: string;
};

export class ApiClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;

  constructor(config: ApiClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, "");
    this.apiKey = config.apiKey;
  }

  async request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
    const method = opts.method ?? "GET";
    const isIdempotent = method === "GET";
    const maxAttempts = 1 + (isIdempotent ? (opts.retries ?? 1) : 0);

    let lastError: ApiError | undefined;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        return await this.attempt<T>(path, method, opts);
      } catch (e) {
        if (!(e instanceof ApiError)) throw e;
        lastError = e;
        // Only retry idempotent GETs on transient (network/5xx/429) failures.
        const transient = e.retryable || e.kind === "network";
        if (!isIdempotent || !transient || attempt === maxAttempts) throw e;
        await sleep(backoffMs(attempt));
      }
    }
    throw lastError ?? new ApiError({ kind: "unknown", status: 0, message: "Request failed." });
  }

  private async attempt<T>(
    path: string,
    method: string,
    opts: RequestOptions,
  ): Promise<T> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);
    const onExternalAbort = () => controller.abort();
    opts.signal?.addEventListener("abort", onExternalAbort, { once: true });

    const headers: Record<string, string> = { Accept: "application/json", ...opts.headers };
    let payload: BodyInit | undefined;
    if (opts.body !== undefined) {
      if (opts.body instanceof FormData) {
        payload = opts.body; // let the runtime set the multipart boundary
      } else {
        headers["Content-Type"] = "application/json";
        payload = JSON.stringify(opts.body);
      }
    }
    if (this.apiKey) headers["X-API-Key"] = this.apiKey;

    try {
      const res = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers,
        body: payload,
        signal: controller.signal,
        cache: "no-store",
      });
      if (!res.ok) throw await toApiError(res);
      if (res.status === 204) return undefined as T;
      const text = await res.text();
      return (text ? JSON.parse(text) : undefined) as T;
    } catch (e) {
      if (e instanceof ApiError) throw e;
      throw toNetworkError(e);
    } finally {
      clearTimeout(timeout);
      opts.signal?.removeEventListener("abort", onExternalAbort);
    }
  }

  get<T>(path: string, opts?: Omit<RequestOptions, "method" | "body">): Promise<T> {
    return this.request<T>(path, { ...opts, method: "GET" });
  }
  post<T>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method">): Promise<T> {
    return this.request<T>(path, { ...opts, method: "POST", body });
  }
  patch<T>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method">): Promise<T> {
    return this.request<T>(path, { ...opts, method: "PATCH", body });
  }
}

function backoffMs(attempt: number): number {
  return Math.min(1000 * 2 ** (attempt - 1), 4000);
}
function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
