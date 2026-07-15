import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/api/server";
import { setSession, clearSession, type Role } from "@/lib/auth/session";

/**
 * Login (Sesi 4.2 / 11.1): validate an API key against the backend, then store
 * it in an httpOnly cookie. There is no whoami endpoint, so we validate by
 * calling an authenticated route and infer the role from which one accepts the
 * key: developers own GET /jobs, providers own GET /providers/me. A 403 on the
 * developer route means the key is valid but belongs to a provider, so we try
 * the provider route before rejecting.
 */
async function detectRole(apiKey: string): Promise<Role | "invalid" | "error"> {
  const asDev = await backendFetch("/jobs?limit=1", { apiKey });
  if (asDev.status === 200) return "developer";
  if (asDev.status !== 401 && asDev.status !== 403) return "error";

  const asProvider = await backendFetch("/providers/me", { apiKey });
  if (asProvider.status === 200) return "provider";
  if (asProvider.status === 401 || asProvider.status === 403) return "invalid";
  return "error";
}

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

  const role = await detectRole(apiKey);
  if (role === "invalid") {
    return NextResponse.json({ message: "That API key isn't valid." }, { status: 401 });
  }
  if (role === "error") {
    return NextResponse.json({ message: "Couldn't verify your key. Try again." }, { status: 502 });
  }

  await setSession(apiKey, role === "provider" ? "Provider" : "Developer", role);
  return NextResponse.json({ ok: true, role });
}

/** Logout (Sesi 4.2): clear the session cookies. */
export async function DELETE() {
  await clearSession();
  return NextResponse.json({ ok: true });
}
