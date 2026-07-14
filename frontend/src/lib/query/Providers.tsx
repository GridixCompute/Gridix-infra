"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  QueryClient,
  QueryClientProvider,
  QueryCache,
  MutationCache,
} from "@tanstack/react-query";
import { isApiError } from "@/lib/api/errors";

/**
 * App-wide data provider (Sesi 3.1 / 3.5). Sensible cache defaults plus one
 * global error policy: a 401 anywhere ends the session and sends the user to
 * login — no infinite spinners, no half-authenticated UI.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  const [client] = useState(() => {
    async function onUnauthorized() {
      // Clear the httpOnly cookie server-side, then bounce to login.
      await fetch("/api/session", { method: "DELETE" }).catch(() => {});
      router.replace("/login?next=/dashboard");
    }

    return new QueryClient({
      defaultOptions: {
        queries: {
          staleTime: 15_000,
          gcTime: 5 * 60_000,
          retry: false, // the ApiClient already retries idempotent GETs
          refetchOnWindowFocus: true,
        },
        mutations: { retry: false },
      },
      queryCache: new QueryCache({
        onError: (err) => {
          if (isApiError(err) && err.kind === "unauthorized") void onUnauthorized();
        },
      }),
      mutationCache: new MutationCache({
        onError: (err) => {
          if (isApiError(err) && err.kind === "unauthorized") void onUnauthorized();
        },
      }),
    });
  });

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
