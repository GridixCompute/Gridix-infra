import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/api/server";
import { getSessionKey } from "@/lib/auth/session";

/**
 * Authenticated proxy (Session 4.2 / 4.5). The browser calls same-origin
 * `/api/gw/<backend-path>`; this reads the httpOnly session cookie and forwards
 * to the FastAPI backend with `Authorization: Bearer`. The key never reaches
 * browser JS. Only forwards to the fixed backend base — no open redirect/SSRF.
 */
type Ctx = { params: Promise<{ path: string[] }> };

async function proxy(req: Request, ctx: Ctx): Promise<Response> {
  const apiKey = await getSessionKey();
  if (!apiKey) {
    return NextResponse.json({ detail: "Not signed in." }, { status: 401 });
  }

  const { path } = await ctx.params;
  // Reject path traversal; segments are joined into a backend path only.
  if (path.some((seg) => seg === "..")) {
    return NextResponse.json({ detail: "Bad request." }, { status: 400 });
  }
  const search = new URL(req.url).search;
  const backendPath = `/${path.map(encodeURIComponent).join("/")}${search}`;

  const method = req.method;
  const hasBody = method !== "GET" && method !== "HEAD";
  const contentType = req.headers.get("content-type");

  const res = await backendFetch(backendPath, {
    method,
    apiKey,
    headers: contentType ? { "Content-Type": contentType } : undefined,
    body: hasBody ? await req.arrayBuffer().then((b) => (b.byteLength ? b : null)) : null,
  });

  // Pass status + body through; strip hop-by-hop headers.
  const headers = new Headers();
  const passType = res.headers.get("content-type");
  if (passType) headers.set("content-type", passType);
  const dispo = res.headers.get("content-disposition");
  if (dispo) headers.set("content-disposition", dispo);
  return new NextResponse(res.body, { status: res.status, headers });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
