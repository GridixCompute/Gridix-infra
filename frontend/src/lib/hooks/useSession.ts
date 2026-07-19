"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

/**
 * Client-side session helpers. Reads only the non-sensitive display-name cookie
 * (the API key stays in an httpOnly cookie the browser can't read). Logout hits
 * the server route that clears both cookies.
 */
function readNameCookie(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)gridix_dev=([^;]*)/);
  return match ? decodeURIComponent(match[1]!) : null;
}

/** Where signing out lands: providers can't use the wallet page, so send them their own. */
function signInPath(): string {
  return /(?:^|;\s*)gridix_role=provider(?:;|$)/.test(document.cookie)
    ? "/provider-login"
    : "/login";
}

export function useSession() {
  const router = useRouter();
  const [name, setName] = useState<string | null>(null);

  useEffect(() => {
    setName(readNameCookie());
  }, []);

  const logout = useCallback(async () => {
    // Read the role before clearing, or the cookie is already gone.
    const dest = signInPath();
    await fetch("/api/session", { method: "DELETE" }).catch(() => {});
    router.replace(dest);
    router.refresh();
  }, [router]);

  return { name, logout };
}
