"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/browser";
import { queryKeys } from "@/lib/query/keys";
import { isTerminal, type Job } from "@/lib/api/types";

/** Single job with adaptive polling — stops once the job reaches a terminal state. */
export function useJob(id: string, initialData?: Job) {
  return useQuery({
    queryKey: queryKeys.jobs.detail(id),
    queryFn: ({ signal }) => api.getJob(id, signal),
    initialData,
    refetchInterval: (query) => {
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
