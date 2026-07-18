"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { isApiError } from "@/lib/api/errors";

/**
 * Honest connectivity banner (Session 3.5 / 13.5). Two distinct, non-silent states:
 * the browser is offline (navigator), or the browser is online but GRIDIX's
 * backend is unreachable (every query is failing with a network/5xx error).
 * Neither leaves the user staring at a broken screen wondering what happened.
 */
export function ConnectivityBanner() {
  const qc = useQueryClient();
  const [offline, setOffline] = useState(false);
  const [backendDown, setBackendDown] = useState(false);

  useEffect(() => {
    setOffline(!navigator.onLine);
    const on = () => setOffline(false);
    const off = () => setOffline(true);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);

  useEffect(() => {
    const cache = qc.getQueryCache();
    const evaluate = () => {
      const queries = cache.getAll();
      const anyOk = queries.some((q) => q.state.status === "success");
      const anyUnreachable = queries.some(
        (q) =>
          q.state.status === "error" &&
          isApiError(q.state.error) &&
          (q.state.error.kind === "network" || q.state.error.kind === "server"),
      );
      // Backend is "down" only when nothing is getting through.
      setBackendDown(anyUnreachable && !anyOk);
    };
    evaluate();
    return cache.subscribe(evaluate);
  }, [qc]);

  if (offline) {
    return (
      <Banner>
        You&apos;re offline. GRIDIX will reconnect automatically when your connection returns.
      </Banner>
    );
  }
  if (backendDown) {
    return (
      <Banner>
        Can&apos;t reach GRIDIX right now — retrying automatically. Your data is safe; actions may
        be unavailable until the connection returns.
      </Banner>
    );
  }
  return null;
}

function Banner({ children }: { children: React.ReactNode }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="bg-[var(--color-warning)] px-4 py-1.5 text-center text-xs font-medium text-black"
    >
      {children}
    </div>
  );
}
