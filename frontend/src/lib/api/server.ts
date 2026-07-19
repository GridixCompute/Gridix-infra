import "server-only";
import { env } from "@/lib/config/env";

/**
 * Server→backend client. The ONLY place the developer API key is attached to a
 * request, as `Authorization: Bearer` (Session 4). Used by route handlers; never
 * imported into a client component.
 */
export type BackendInit = {
  method?: string;
  body?: BodyInit | null;
  apiKey?: string;
  headers?: Record<string, string>;
  timeoutMs?: number;
};

/** Low-level: returns the raw Response so a proxy can pass it straight through. */
export async function backendFetch(path: string, init: BackendInit = {}): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), init.timeoutMs ?? 20_000);
  const headers = new Headers(init.headers);
  if (init.apiKey) headers.set("Authorization", `Bearer ${init.apiKey}`);
  try {
    return await fetch(`${env.apiUrl}${path}`, {
      method: init.method ?? "GET",
      headers,
      body: init.body ?? undefined,
      signal: controller.signal,
      cache: "no-store",
    });
  } finally {
    clearTimeout(timeout);
  }
}

/** Typed helper for JSON endpoints. Throws with the backend status on failure. */
export async function backendJson<T>(
  path: string,
  init: Omit<BackendInit, "body"> & { json?: unknown } = {},
): Promise<{ status: number; data: T }> {
  const { json, headers, ...rest } = init;
  const res = await backendFetch(path, {
    ...rest,
    headers: json !== undefined ? { "Content-Type": "application/json", ...headers } : headers,
    body: json !== undefined ? JSON.stringify(json) : undefined,
  });
  const text = await res.text();
  const data = (text ? JSON.parse(text) : undefined) as T;
  return { status: res.status, data };
}
