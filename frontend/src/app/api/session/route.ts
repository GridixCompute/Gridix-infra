import { NextResponse } from "next/server";
import { backendJson } from "@/lib/api/server";
import { setSession, clearSession, type Capability } from "@/lib/auth/session";
import type { Provider, SessionResponse } from "@/lib/api/types";

/**
 * Sign-in: the wallet is the only way in, for everyone.
 *
 * The browser has already fetched a challenge (GET /api/session/nonce) and had the
 * wallet sign it. This forwards address + nonce + signature to POST /auth/verify,
 * which recovers the signer, resolves-or-creates the developer, and mints a session
 * credential. That credential goes straight into the httpOnly cookie — it is never
 * returned to the page.
 *
 * There is deliberately NO API-key branch. An API key lives in scripts, CI, and .env
 * files; if it could also open the dashboard, one leaked key would carry billing and
 * withdraw with it. Keys call the inference API and nothing else.
 *
 * Providers used to be the exception, signing in with an agent key at
 * /api/session/provider because they had no wallet identity backend-side. They do now:
 * the provider capability hangs off the same address (`GET /providers/me` resolves it from
 * the wallet session), so that exception is gone and with it the last route where a
 * long-lived machine key opened a human session.
 */
type VerifyBody = { address?: string; nonce?: string; signature?: string };

/**
 * Which surfaces this address can reach.
 *
 * `developer` always — sign-in resolves-or-creates one. `provider` only if the address
 * owns a Provider record, which is exactly what `GET /providers/me` answers from a wallet
 * session: 200 when it does, 403 when it does not.
 *
 * A failure to answer is treated as "no provider" rather than propagated. This probe
 * decides which links to show, not what anyone may do — the backend re-checks on every
 * request — so a blip here should cost a nav item, never the ability to sign in.
 */
async function capabilitiesFor(sessionKey: string): Promise<Capability[]> {
  const caps: Capability[] = ["developer"];
  try {
    const { status } = await backendJson<Provider>("/providers/me", { apiKey: sessionKey });
    if (status >= 200 && status < 300) caps.push("provider");
  } catch {
    /* leave the provider capability off */
  }
  return caps;
}

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

  const capabilities = await capabilitiesFor(data.api_key);
  await setSession(data.api_key, data.name, capabilities);
  return NextResponse.json({ ok: true, capabilities });
}

/** Logout (Session 4.2): clear the session cookies. */
export async function DELETE() {
  await clearSession();
  return NextResponse.json({ ok: true });
}
