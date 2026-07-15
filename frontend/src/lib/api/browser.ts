"use client";

import { ApiClient } from "./client";
import type {
  Job,
  SubmitJobRequest,
  JobAudit,
  BillingSummary,
  BillingLedgerEntry,
} from "./types";
import type { JobFilters } from "@/lib/query/keys";

/**
 * Browser API surface (Sesi 3.2). Every call goes through the same-origin
 * authenticated proxy (/api/gw). Components never call fetch directly and never
 * see the API key. All return types come from the generated OpenAPI schema.
 */
const gw = new ApiClient({ baseUrl: "/api/gw" });

function jobsQuery(filters: JobFilters): string {
  const p = new URLSearchParams();
  if (filters.limit != null) p.set("limit", String(filters.limit));
  if (filters.offset != null) p.set("offset", String(filters.offset));
  const q = p.toString();
  return q ? `?${q}` : "";
}

export const api = {
  listJobs(filters: JobFilters = {}, signal?: AbortSignal): Promise<Job[]> {
    return gw.get<Job[]>(`/jobs${jobsQuery(filters)}`, { signal, retries: 2 });
  },
  getJob(id: string, signal?: AbortSignal): Promise<Job> {
    return gw.get<Job>(`/jobs/${id}`, { signal, retries: 2 });
  },
  getJobAudit(id: string, signal?: AbortSignal): Promise<JobAudit> {
    return gw.get<JobAudit>(`/jobs/${id}/audit`, { signal, retries: 2 });
  },
  submitJob(body: SubmitJobRequest): Promise<Job> {
    return gw.post<Job>("/jobs", body);
  },
  billingSummary(signal?: AbortSignal): Promise<BillingSummary> {
    return gw.get<BillingSummary>("/billing/summary", { signal, retries: 2 });
  },
  billingLedger(limit = 200, signal?: AbortSignal): Promise<BillingLedgerEntry[]> {
    return gw.get<BillingLedgerEntry[]>(`/billing/ledger?limit=${limit}`, { signal, retries: 2 });
  },
};
