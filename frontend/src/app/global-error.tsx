"use client";

import { useEffect } from "react";
import { reportError } from "@/lib/observability/report";

/**
 * Root error boundary (Session 14.4). Catches failures in the root layout itself —
 * it must render its own <html>/<body>. Reports the error (scrubbed) and gives
 * the user a way out.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    reportError(error, { boundary: "global", digest: error.digest });
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          minHeight: "100dvh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "1rem",
          background: "#05070a",
          color: "#eef3f7",
          fontFamily: "system-ui, sans-serif",
          textAlign: "center",
          padding: "1.5rem",
        }}
      >
        <h1 style={{ fontSize: "1.25rem", fontWeight: 700 }}>Something went wrong</h1>
        <p style={{ maxWidth: "28rem", color: "#7e8c98", fontSize: "0.875rem" }}>
          GRIDIX hit an unexpected error and couldn&apos;t load. It&apos;s been reported — please
          try again.
        </p>
        <button
          onClick={reset}
          style={{
            background: "#a6e610",
            color: "#000",
            border: "none",
            borderRadius: "0.5rem",
            padding: "0.5rem 1rem",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Reload
        </button>
      </body>
    </html>
  );
}
