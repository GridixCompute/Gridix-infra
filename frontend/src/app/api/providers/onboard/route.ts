import { NextResponse } from "next/server";
import { backendJson } from "@/lib/api/server";
import { getSessionKey, setCapabilities } from "@/lib/auth/session";
import type { RegisteredPrincipal } from "@/lib/api/types";

/**
 * Add the provider capability to the signed-in wallet address, and reveal the node's agent
 * key exactly once.
 *
 * This replaces the deleted `POST /api/providers`, and the difference is the whole point of
 * the change. That route called the backend's `POST /providers`, which creates a Provider
 * with NO wallet address and then signed the browser in AS that provider using its agent
 * key. Two problems, both now gone: a machine credential opened a human session, and the
 * resulting Provider row was unreachable by any wallet session — so the operator could
 * never sign in again once key-based login went away.
 *
 * Here the session must already exist (a wallet session, since that is the only kind), and
 * the backend binds the new Provider to that address. The returned key is FOR THE NODE. It
 * is shown once and never stored in a cookie: the operator signs in with the same wallet
 * they used to get here.
 */
export async function POST(req: Request) {
  const sessionKey = await getSessionKey();
  if (!sessionKey) {
    return NextResponse.json({ message: "Sign in with your wallet first." }, { status: 401 });
  }

  let name = "";
  let region: string | undefined;
  try {
    const body = (await req.json()) as { name?: string; region?: string };
    name = body.name ?? "";
    region = body.region?.trim() || undefined;
  } catch {
    /* fall through to validation */
  }
  if (!name.trim()) {
    return NextResponse.json({ message: "Enter a name for your provider." }, { status: 422 });
  }

  const { status, data } = await backendJson<RegisteredPrincipal>("/providers/onboard", {
    method: "POST",
    apiKey: sessionKey,
    json: { name: name.trim(), region },
  });

  if (status === 409) {
    return NextResponse.json(
      { message: "This wallet is already registered as a provider." },
      { status: 409 },
    );
  }
  if (status === 401 || status === 403) {
    // The backend gates onboarding on a WALLET session specifically, because minting a
    // credential from a credential makes revocation meaningless.
    return NextResponse.json(
      { message: "Sign in with your wallet to become a provider." },
      { status: 401 },
    );
  }
  if (status < 200 || status >= 300) {
    return NextResponse.json({ message: "Couldn't register your node. Try again." }, { status });
  }

  // The session is unchanged — same address, same credential. Only the routing hint moves,
  // so the console opens without making the operator sign in again.
  await setCapabilities(["developer", "provider"]);

  // `apiKey` is returned to the page for a one-time reveal and deliberately NOT written to
  // any cookie. It belongs in the node's environment, not in this browser.
  return NextResponse.json({ id: data.id, name: data.name, apiKey: data.api_key });
}
