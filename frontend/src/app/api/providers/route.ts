import { NextResponse } from "next/server";
import { backendJson } from "@/lib/api/server";
import { setSession } from "@/lib/auth/session";
import type { RegisteredPrincipal } from "@/lib/api/types";

/**
 * Register a provider (Sesi 11.1). Mirrors developer registration: forwards to
 * the backend, logs the provider in via the httpOnly session cookie, and
 * returns the agent API key ONCE for the operator to copy into their node's
 * environment. After that the key only lives in the cookie.
 */
export async function POST(req: Request) {
  let name = "";
  let region: string | undefined;
  try {
    const body = (await req.json()) as { name?: string; region?: string };
    name = body.name ?? "";
    region = body.region?.trim() || undefined;
  } catch {
    /* fall through to validation */
  }
  if (!name || !name.trim()) {
    return NextResponse.json({ message: "Enter a name for your provider." }, { status: 422 });
  }

  const { status, data } = await backendJson<RegisteredPrincipal>("/providers", {
    method: "POST",
    json: { name: name.trim(), region },
  });

  if (status < 200 || status >= 300) {
    return NextResponse.json({ message: "Couldn't create your provider. Try again." }, { status });
  }

  await setSession(data.api_key, data.name, "provider");
  return NextResponse.json({ id: data.id, name: data.name, apiKey: data.api_key });
}
