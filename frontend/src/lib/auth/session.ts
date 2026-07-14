import "server-only";
import { cookies } from "next/headers";

/**
 * Server-only session handling (Sesi 4.2 / 4.5). The developer API key lives in
 * an httpOnly cookie so browser JS can never read it. A separate, non-sensitive
 * cookie carries the display name only.
 */
export const SESSION_COOKIE = "gridix_session";
export const NAME_COOKIE = "gridix_dev";

const COMMON = {
  path: "/",
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  maxAge: 60 * 60 * 24 * 30, // 30 days
};

export async function getSessionKey(): Promise<string | undefined> {
  return (await cookies()).get(SESSION_COOKIE)?.value;
}

export async function setSession(apiKey: string, name: string): Promise<void> {
  const jar = await cookies();
  jar.set(SESSION_COOKIE, apiKey, { ...COMMON, httpOnly: true });
  // Display-only; readable by the client so the UI can greet the developer.
  jar.set(NAME_COOKIE, name, { ...COMMON, httpOnly: false });
}

export async function clearSession(): Promise<void> {
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
  jar.delete(NAME_COOKIE);
}
