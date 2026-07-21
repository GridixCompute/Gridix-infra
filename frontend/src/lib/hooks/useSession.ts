"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

/**
 * Client-side session helpers. Reads only the non-sensitive cookies — the session
 * credential stays in an httpOnly cookie the browser can't read. Logout hits the server
 * route that clears all of them.
 */
function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]!) : null;
}

export type Capability = "developer" | "provider";

export function useSession() {
  const router = useRouter();
  const [name, setName] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<Capability[]>([]);

  useEffect(() => {
    setName(readCookie("gridix_dev"));
    const raw = readCookie("gridix_caps") ?? "";
    const present = raw.split(",").map((c) => c.trim());
    setCapabilities((["developer", "provider"] as Capability[]).filter((c) => present.includes(c)));
  }, []);

  const logout = useCallback(async () => {
    await fetch("/api/session", { method: "DELETE" }).catch(() => {});
    // One sign-in page now, so no need to work out which one this principal came from —
    // the old version read the role cookie before clearing it, to pick between two.
    router.replace("/login");
    router.refresh();
  }, [router]);

  /**
   * A routing/display hint only. The backend re-checks every request, so a page shown on a
   * forged cookie simply fails its own API calls — this never decides what anyone may do.
   */
  const isProvider = capabilities.includes("provider");

  return { name, capabilities, isProvider, logout };
}
