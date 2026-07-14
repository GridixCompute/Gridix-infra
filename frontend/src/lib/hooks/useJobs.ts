"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/browser";
import { queryKeys, type JobFilters } from "@/lib/query/keys";
import { isTerminal, type Job } from "@/lib/api/types";
import { useRealtime } from "@/lib/realtime/RealtimeProvider";

const ACTIVE_POLL_MS = 4000;

/**
 * List jobs. Adaptive polling: poll only while at least one job is non-terminal.
 * When the real-time SSE stream is connected, polling pauses entirely and
 * updates arrive as push; if the stream drops, polling resumes as the fallback.
 */
export function useJobs(filters: JobFilters = {}) {
  const { connected } = useRealtime();
  return useQuery({
    queryKey: queryKeys.jobs.list(filters),
    queryFn: ({ signal }) => api.listJobs(filters, signal),
    refetchInterval: (query) => {
      if (connected) return false; // live via SSE
      const jobs = query.state.data as Job[] | undefined;
      const anyActive = jobs?.some((j) => !isTerminal(j.status)) ?? false;
      return anyActive ? ACTIVE_POLL_MS : false;
    },
  });
}
