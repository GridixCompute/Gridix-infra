"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/browser";
import { queryKeys, type JobFilters } from "@/lib/query/keys";
import { isTerminal, type Job } from "@/lib/api/types";

const ACTIVE_POLL_MS = 4000;

/**
 * List jobs (Sesi 3.2). Adaptive polling (Sesi 3.4): poll only while at least
 * one job is non-terminal; stop once everything has settled. The browser
 * throttles timers in background tabs, so idle tabs don't flood the API.
 */
export function useJobs(filters: JobFilters = {}) {
  return useQuery({
    queryKey: queryKeys.jobs.list(filters),
    queryFn: ({ signal }) => api.listJobs(filters, signal),
    refetchInterval: (query) => {
      const jobs = query.state.data as Job[] | undefined;
      const anyActive = jobs?.some((j) => !isTerminal(j.status)) ?? false;
      return anyActive ? ACTIVE_POLL_MS : false;
    },
  });
}
