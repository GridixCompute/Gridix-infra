/**
 * Friendly aliases over the generated OpenAPI schema. These are the ONLY names
 * the app imports for domain types — never hand-write a shape the backend owns.
 * Regenerate with `pnpm gen:types` when the backend schema changes (CI gate,
 * Sesi 1.3, fails the build if this drifts).
 */
import type { components } from "./schema";

type S = components["schemas"];

export type Job = S["JobResponse"];
export type JobStatus = S["JobStatus"];
export type JobKind = S["JobKind"];
export type SubmitJobRequest = S["SubmitJobRequest"];
export type ResourceSpec = S["ResourceSpec"];
export type JobAudit = S["JobAudit"];
export type AttemptRecord = S["AttemptRecord"];
export type LedgerRecord = S["LedgerRecord"];
export type Provider = S["ProviderResponse"];
export type ProviderCapabilities = S["ProviderCapabilities"];
export type ProviderJobAttempt = S["ProviderJobAttempt"];
export type ReputationEvent = S["ReputationEventResponse"];
export type RegisterDeveloperRequest = S["RegisterDeveloperRequest"];
export type RegisterProviderRequest = S["RegisterProviderRequest"];
export type RegisteredPrincipal = S["RegisteredPrincipal"];
export type HealthResponse = S["HealthResponse"];
export type BenchmarkResponse = S["BenchmarkResponse"];
export type BandwidthResponse = S["BandwidthResponse"];
export type DisputeResponse = S["DisputeResponse"];
export type BillingLedgerEntry = S["BillingLedgerEntry"];
export type BillingSummary = S["BillingSummary"];
export type BlobRef = S["BlobRef"];

/** All job statuses in lifecycle order — the single source for UI ordering. */
export const JOB_STATUSES: readonly JobStatus[] = [
  "queued",
  "assigned",
  "running",
  "completed",
  "failed",
  "timeout",
] as const;

export const TERMINAL_STATUSES: ReadonlySet<JobStatus> = new Set<JobStatus>([
  "completed",
  "failed",
  "timeout",
]);

export function isTerminal(status: JobStatus): boolean {
  return TERMINAL_STATUSES.has(status);
}
