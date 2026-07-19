"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/Button";
import { reportError } from "@/lib/observability/report";

/**
 * Route error boundary (Session 14.4). Catches render/runtime errors below the root
 * layout, reports them (scrubbed of any secrets), and offers a real recovery —
 * never a blank white screen.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    reportError(error, { boundary: "route", digest: error.digest });
  }, [error]);

  return (
    <div className="flex min-h-[60dvh] flex-col items-center justify-center gap-4 px-6 text-center">
      <div
        className="flex h-12 w-12 items-center justify-center rounded-full border border-[#ff5c5c55] bg-[#ff5c5c1a] text-lg text-[var(--color-danger)]"
        aria-hidden="true"
      >
        !
      </div>
      <h1 className="text-xl font-[var(--font-display)] font-semibold text-[var(--color-ink)]">
        Something went wrong
      </h1>
      <p className="max-w-md text-sm text-[var(--color-ink-faint)]">
        An unexpected error interrupted this page. It&apos;s been reported. You can retry, or head
        back to your dashboard.
      </p>
      <div className="mt-1 flex gap-3">
        <Button onClick={reset}>Try again</Button>
        <a href="/dashboard">
          <Button variant="secondary">Go to dashboard</Button>
        </a>
      </div>
    </div>
  );
}
