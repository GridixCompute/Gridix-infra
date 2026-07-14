import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/api/server";
import { setSession, clearSession } from "@/lib/auth/session";

/**
 * Login (Sesi 4.2): validate an API key against the backend, then store it in
 * an httpOnly cookie. There is no developer whoami endpoint, so we validate by
 * calling an authenticated developer route (GET /jobs) — 200 = valid key.
 */
export async function POST(req: Request) {
  let apiKey = "";
  try {
    const body = (await req.json()) as { apiKey?: string };
    apiKey = body.apiKey ?? "";
  } catch {
    /* fall through */
  }
  apiKey = apiKey.trim();
  if (!apiKey) {
    return NextResponse.json({ message: "Paste your API key." }, { status: 422 });
  }

  const res = await backendFetch("/jobs?limit=1", { apiKey });
  if (res.status === 200) {
    await setSession(apiKey, "Developer");
    return NextResponse.json({ ok: true });
  }
  if (res.status === 401 || res.status === 403) {
    return NextResponse.json({ message: "That API key isn't valid." }, { status: 401 });
  }
  return NextResponse.json({ message: "Couldn't verify your key. Try again." }, { status: 502 });
}

/** Logout (Sesi 4.2): clear the session cookies. */
export async function DELETE() {
  await clearSession();
  return NextResponse.json({ ok: true });
}
