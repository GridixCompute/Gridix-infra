"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { providerApi } from "@/lib/api/providerBrowser";
import { queryKeys } from "@/lib/query/keys";
import type { ProviderCapabilities } from "@/lib/api/types";

/** The authenticated provider's own record. Refetched periodically so the
 *  connection/health status on the console stays fresh. */
export function useProviderMe() {
  return useQuery({
    queryKey: queryKeys.provider.me,
    queryFn: ({ signal }) => providerApi.me(signal),
    refetchInterval: 10_000,
  });
}

export function useProviderBenchmark() {
  return useQuery({
    queryKey: queryKeys.provider.benchmark,
    queryFn: ({ signal }) => providerApi.benchmark(signal),
  });
}

export function useProviderTrust() {
  return useQuery({
    queryKey: queryKeys.provider.trust,
    queryFn: ({ signal }) => providerApi.trust(signal),
  });
}

export function useProviderBandwidth() {
  return useQuery({
    queryKey: queryKeys.provider.bandwidth,
    queryFn: ({ signal }) => providerApi.bandwidth(signal),
    refetchInterval: 15_000,
  });
}

export function useProviderJobs(limit = 50) {
  return useQuery({
    queryKey: queryKeys.provider.jobs(limit),
    queryFn: ({ signal }) => providerApi.jobs(limit, signal),
    refetchInterval: 10_000,
  });
}

export function useProviderReputation(limit = 50) {
  return useQuery({
    queryKey: queryKeys.provider.reputation(limit),
    queryFn: ({ signal }) => providerApi.reputation(limit, signal),
  });
}

export function useProviderDisputes() {
  return useQuery({
    queryKey: queryKeys.provider.disputes,
    queryFn: ({ signal }) => providerApi.disputes(signal),
  });
}

/** Update declared capabilities (PATCH /providers/me), then refresh the record. */
export function useUpdateCapabilities() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ProviderCapabilities) => providerApi.updateCapabilities(body),
    onSuccess: (updated) => {
      qc.setQueryData(queryKeys.provider.me, updated);
    },
  });
}

/** Contest an open slash → moves it to review. Refreshes the dispute list. */
export function useContestDispute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => providerApi.contestDispute(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.provider.disputes });
    },
  });
}
