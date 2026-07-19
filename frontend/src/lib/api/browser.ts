"use client";

import { ApiClient } from "./client";
import type {
  Job,
  SubmitJobRequest,
  JobAudit,
  BillingSummary,
  BillingLedgerEntry,
  BlobRef,
} from "./types";
import type { JobFilters } from "@/lib/query/keys";

/**
 * Browser API surface (Session 3.2). Every call goes through the same-origin
 * authenticated proxy (/api/gw). Components never call fetch directly and never
 * see the API key. All return types come from the generated OpenAPI schema.
 */
const gw = new ApiClient({ baseUrl: "/api/gw" });

/** Mirrors the backend's per-blob guardrail (api/app/routes/blobs.py). */
export const MAX_BLOB_BYTES = 256 * 1024 * 1024;

// A blob upload is a body transfer, not a round trip — the 15s default would abort
// any real dataset mid-flight.
const UPLOAD_TIMEOUT_MS = 10 * 60_000;

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
  /** Stage a job's input data; the returned ref becomes the job's `input_ref`. */
  uploadBlob(file: File, signal?: AbortSignal): Promise<BlobRef> {
    const form = new FormData();
    form.append("file", file);
    return gw.post<BlobRef>("/blobs", form, { signal, timeoutMs: UPLOAD_TIMEOUT_MS });
  },
  billingSummary(signal?: AbortSignal): Promise<BillingSummary> {
    return gw.get<BillingSummary>("/billing/summary", { signal, retries: 2 });
  },
  billingLedger(limit = 200, signal?: AbortSignal): Promise<BillingLedgerEntry[]> {
    return gw.get<BillingLedgerEntry[]>(`/billing/ledger?limit=${limit}`, { signal, retries: 2 });
  },
};
