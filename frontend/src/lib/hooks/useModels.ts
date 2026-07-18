"use client";

import { useQuery } from "@tanstack/react-query";
import { listModels } from "@/lib/inference/client";
import { queryKeys } from "@/lib/query/keys";

/**
 * The models the network serves, with their rate card (Session 4.1 / 5.4).
 *
 * Long stale time on purpose: the catalogue and its prices change on the order of releases,
 * not seconds — unlike balance, which must stay fresh. Availability can flip when providers
 * come and go, which is what the refetch interval is for.
 *
 * ⚠️ Served by the mock today — there is no GET /v1/models.
 */
export function useModels() {
  return useQuery({
    queryKey: queryKeys.inference.models,
    queryFn: ({ signal }) => listModels(signal),
    staleTime: 5 * 60_000,
    refetchInterval: 60_000,
  });
}
