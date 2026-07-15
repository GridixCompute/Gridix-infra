"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/browser";
import { queryKeys } from "@/lib/query/keys";

/** Authoritative period totals derived from the backend ledger (Sesi 10.3). */
export function useBillingSummary() {
  return useQuery({
    queryKey: queryKeys.billing.summary,
    queryFn: ({ signal }) => api.billingSummary(signal),
    refetchInterval: 20_000,
  });
}

/** Every ledger leg across the developer's jobs (Sesi 10.1). */
export function useBillingLedger(limit = 200) {
  return useQuery({
    queryKey: queryKeys.billing.ledger(limit),
    queryFn: ({ signal }) => api.billingLedger(limit, signal),
    refetchInterval: 20_000,
  });
}
