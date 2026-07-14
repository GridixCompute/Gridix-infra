"use client";

import { useEffect, useState } from "react";

/** Honest offline banner (Sesi 3.5) — no silent failures when the network drops. */
export function OfflineBanner() {
  const [online, setOnline] = useState(true);

  useEffect(() => {
    setOnline(navigator.onLine);
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);

  if (online) return null;
  return (
    <div
      role="status"
      className="bg-[var(--color-warning)] px-4 py-1.5 text-center text-xs font-medium text-black"
    >
      You&apos;re offline. GRIDIX will reconnect automatically when your connection returns.
    </div>
  );
}
