import "server-only";
import { cookies } from "next/headers";

/**
 * Server-only session handling. The session credential lives in an httpOnly cookie so
 * browser JS can never read it; a separate, non-sensitive cookie carries the display name.
 *
 * CAPABILITIES, NOT A ROLE. There used to be a `gridix_role` cookie holding exactly one of
 * "developer" | "provider", and the middleware bounced each principal out of the other's
 * area. That model is gone: one wallet address is one identity, and the same address can be
 * both — a developer who also runs a node signs in once and reaches both surfaces. A single
 * `role` value cannot express that; it would have to pick one and lock the person out of
 * half their own account.
 *
 * So the cookie is a SET. `developer` comes with having a session at all (wallet sign-in
 * resolves-or-creates a developer), and `provider` is added when the signed-in address owns
 * a Provider record. The middleware reads it to decide whether the provider console opens;
 * the backend re-checks on every request, so this cookie is a routing hint, never the
 * authority. Forging it gets you a page whose own API calls then fail.
 */
export const SESSION_COOKIE = "gridix_session";
export const NAME_COOKIE = "gridix_dev";
export const CAPS_COOKIE = "gridix_caps";

export type Capability = "developer" | "provider";

const COMMON = {
  path: "/",
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  maxAge: 60 * 60 * 24 * 30, // 30 days
};

export async function getSessionKey(): Promise<string | undefined> {
  return (await cookies()).get(SESSION_COOKIE)?.value;
}

/** Sorted and de-duplicated, so the cookie value is stable for a given capability set. */
export function serialiseCapabilities(caps: Capability[]): string {
  return [...new Set(caps)].sort().join(",");
}

/** Read a capability set back, keeping only names this build knows. */
export function parseCapabilities(raw: string | undefined): Capability[] {
  if (!raw) return [];
  const present = raw.split(",").map((c) => c.trim());
  const known: Capability[] = ["developer", "provider"];
  return known.filter((c) => present.includes(c));
}

export async function setSession(apiKey: string, name: string, caps: Capability[]): Promise<void> {
  const jar = await cookies();
  jar.set(SESSION_COOKIE, apiKey, { ...COMMON, httpOnly: true });
  // Display/routing only, readable by the client so the UI can greet the principal and show
  // the surfaces they actually have. Neither is sensitive; the key stays httpOnly.
  jar.set(NAME_COOKIE, name, { ...COMMON, httpOnly: false });
  jar.set(CAPS_COOKIE, serialiseCapabilities(caps), { ...COMMON, httpOnly: false });
}

/** Update the capability hint without re-minting the session (e.g. right after onboarding). */
export async function setCapabilities(caps: Capability[]): Promise<void> {
  const jar = await cookies();
  jar.set(CAPS_COOKIE, serialiseCapabilities(caps), { ...COMMON, httpOnly: false });
}

export async function clearSession(): Promise<void> {
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
  jar.delete(NAME_COOKIE);
  jar.delete(CAPS_COOKIE);
}
