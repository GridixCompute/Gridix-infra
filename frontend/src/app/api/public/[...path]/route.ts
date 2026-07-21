import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/api/server";
import { getSessionKey } from "@/lib/auth/session";

/**
 * Same-origin proxy for the free tier, `/api/public/*` -> backend `/public/*`.
 *
 * Separate from `/api/gw` because that proxy REFUSES anonymous callers — it 401s without a
 * session cookie, which is right for the paid API and wrong for a playground whose whole
 * point is that chat needs no account. This one forwards the session WHEN THERE IS ONE and
 * proxies anonymously when there is not, which is exactly the shape the free tier needs:
 * chat is open, images are wallet-gated, and the backend decides which is which.
 *
 * ⚠️ THE PATH PREFIX IS FIXED. Every request is rewritten under `/public/`, so this cannot
 * be used to reach `/v1`, `/jobs`, or anything else. Without that, an unauthenticated proxy
 * that forwarded arbitrary paths would be a hole straight through the app's authentication —
 * a caller could hit any backend route from the browser with no session at all. The prefix is
 * the security boundary, not a convenience.
 *
 * Going through a proxy at all, rather than calling the backend origin from the browser:
 * the CSP allows `connect-src 'self'` and the chain RPC, so a direct cross-origin call to
 * the coordinator is blocked before it leaves the page — and would need CORS besides.
 */
type Ctx = { params: Promise<{ path: string[] }> };

async function proxy(req: Request, ctx: Ctx): Promise<Response> {
  const { path } = await ctx.params;
  if (path.some((seg) => seg === "..")) {
    return NextResponse.json({ detail: "Bad request." }, { status: 400 });
  }

  const search = new URL(req.url).search;
  const backendPath = `/public/${path.map(encodeURIComponent).join("/")}${search}`;

  // Present for a signed-in visitor, absent for an anonymous one. Both are valid here.
  const apiKey = await getSessionKey();

  const method = req.method;
  const hasBody = method !== "GET" && method !== "HEAD";
  const contentType = req.headers.get("content-type");

  const res = await backendFetch(backendPath, {
    method,
    apiKey,
    headers: contentType ? { "Content-Type": contentType } : undefined,
    body: hasBody ? await req.arrayBuffer().then((b) => (b.byteLength ? b : null)) : null,
  });

  const headers = new Headers();
  const passType = res.headers.get("content-type");
  if (passType) headers.set("content-type", passType);
  // Chat is streamed, so the body is passed through unbuffered and proxy buffering is
  // disabled — buffering here would collect the whole reply and defeat the streaming.
  headers.set("Cache-Control", "no-cache, no-transform");
  headers.set("X-Accel-Buffering", "no");
  return new NextResponse(res.body, { status: res.status, headers });
}

export const GET = proxy;
export const POST = proxy;
