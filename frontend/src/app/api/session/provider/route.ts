import { NextResponse } from "next/server";
import { backendJson } from "@/lib/api/server";
import { setSession } from "@/lib/auth/session";
import type { Provider } from "@/lib/api/types";

/**
 * Provider sign-in with the agent key.
 *
 * This is the one place an API key still opens a session, and it is narrow on purpose.
 * Developers sign in with their wallet (POST /api/session); a developer key presented
 * here does NOT work, because the only thing it is checked against is GET /providers/me,
 * which a developer key cannot read. So the property the wallet-only change buys —
 * a leaked developer key cannot reach billing or withdraw — holds regardless of what
 * is pasted here.
 *
 * Providers get this exception because they have no wallet identity backend-side:
 * /auth/verify resolves developers only. When provider wallet auth lands, this route
 * goes away with it.
 */
export async function POST(req: Request) {
  let apiKey = "";
  try {
    const body = (await req.json()) as { apiKey?: string };
    apiKey = body.apiKey ?? "";
  } catch {
    /* fall through to validation */
  }
  apiKey = apiKey.trim();
  if (!apiKey) {
    return NextResponse.json({ message: "Paste your agent key." }, { status: 422 });
  }

  const { status, data } = await backendJson<Provider>("/providers/me", { apiKey });

  if (status === 401 || status === 403) {
    return NextResponse.json({ message: "That agent key isn't valid." }, { status: 401 });
  }
  if (status < 200 || status >= 300) {
    return NextResponse.json({ message: "Couldn't verify your key. Try again." }, { status: 502 });
  }

  await setSession(apiKey, data.name, "provider");
  return NextResponse.json({ ok: true, role: "provider" });
}
