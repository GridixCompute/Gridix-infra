"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/browser";
import { queryKeys } from "@/lib/query/keys";
import { isTerminal, type Job } from "@/lib/api/types";
import { useRealtime } from "@/lib/realtime/RealtimeProvider";

/**
 * Single job. Polls while non-terminal, but pauses when the SSE stream is
 * connected (updates arrive as push); polling resumes if the stream drops.
 */
export function useJob(id: string, initialData?: Job) {
  const { connected } = useRealtime();
  return useQuery({
    queryKey: queryKeys.jobs.detail(id),
    queryFn: ({ signal }) => api.getJob(id, signal),
    initialData,
    refetchInterval: (query) => {
      if (connected) return false; // live via SSE
      const job = query.state.data as Job | undefined;
      return job && !isTerminal(job.status) ? 3000 : false;
    },
  });
}

export function useJobAudit(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.jobs.audit(id),
    queryFn: ({ signal }) => api.getJobAudit(id, signal),
    enabled,
    staleTime: 30_000,
  });
}
