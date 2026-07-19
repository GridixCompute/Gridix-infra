import { NextResponse } from "next/server";
import { backendJson } from "@/lib/api/server";
import { setSession, clearSession } from "@/lib/auth/session";
import type { SessionResponse } from "@/lib/api/types";

/**
 * Developer sign-in: the wallet is the only way in.
 *
 * The browser has already fetched a challenge (GET /api/session/nonce) and had the
 * wallet sign it. This forwards address + nonce + signature to POST /auth/verify,
 * which recovers the signer, resolves-or-creates the developer, and mints a session
 * credential. That credential goes straight into the httpOnly cookie — it is never
 * returned to the page.
 *
 * There is deliberately NO API-key branch here. An API key lives in scripts, CI, and
 * .env files; if it could also open the dashboard, one leaked key would carry billing
 * and withdraw with it. Keys call the inference API and nothing else. Providers, which
 * have no wallet identity backend-side, sign in at /api/session/provider.
 */
type VerifyBody = { address?: string; nonce?: string; signature?: string };

export async function POST(req: Request) {
  let body: VerifyBody = {};
  try {
    body = (await req.json()) as VerifyBody;
  } catch {
    /* fall through to validation */
  }

  const address = body.address?.trim() ?? "";
  const nonce = body.nonce?.trim() ?? "";
  const signature = body.signature?.trim() ?? "";
  if (!address || !nonce || !signature) {
    return NextResponse.json({ message: "Sign the message to continue." }, { status: 422 });
  }

  const { status, data } = await backendJson<SessionResponse>("/auth/verify", {
    method: "POST",
    json: { address, nonce, signature },
  });

  if (status === 401) {
    return NextResponse.json(
      { message: "That signature didn't check out. Try connecting again." },
      { status: 401 },
    );
  }
  if (status < 200 || status >= 300) {
    return NextResponse.json({ message: "Couldn't sign you in. Try again." }, { status: 502 });
  }

  await setSession(data.api_key, data.name, "developer");
  return NextResponse.json({ ok: true, role: "developer" });
}

/** Logout (Session 4.2): clear the session cookies. */
export async function DELETE() {
  await clearSession();
  return NextResponse.json({ ok: true });
}
