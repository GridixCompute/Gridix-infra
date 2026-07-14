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

export function useSession() {
  const router = useRouter();
  const [name, setName] = useState<string | null>(null);

  useEffect(() => {
    setName(readNameCookie());
  }, []);

  const logout = useCallback(async () => {
    await fetch("/api/session", { method: "DELETE" }).catch(() => {});
    router.replace("/login");
    router.refresh();
  }, [router]);

  return { name, logout };
}
