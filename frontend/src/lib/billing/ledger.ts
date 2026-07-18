import type { BillingLedgerEntry } from "@/lib/api/types";

/**
 * Client-side shaping of the raw ledger (Session 10.1/10.2/10.4). The backend owns
 * the numbers; here we only group and sum the exact rows it returned — never
 * invent or round a figure. A per-job breakdown derived from the same legs is
 * guaranteed to reconcile to the total charged.
 */
export type JobBreakdown = {
  jobId: string;
  entries: BillingLedgerEntry[];
  escrowed: number; // held at submit
  providerPaid: number; // net to the provider
  protocolFee: number; // protocol's cut of the settle
  dataCost: number; // egress / data movement
  refunded: number; // unused escrow returned
  totalCharged: number; // providerPaid + protocolFee + dataCost (== cost_final)
  latestAt: string;
};

function sum(entries: BillingLedgerEntry[], pred: (e: BillingLedgerEntry) => boolean): number {
  return entries.reduce((acc, e) => (pred(e) ? acc + e.amount : acc), 0);
}

/** Group ledger legs by job and compute the exact per-job cost breakdown, newest first. */
export function groupByJob(entries: BillingLedgerEntry[]): JobBreakdown[] {
  const byJob = new Map<string, BillingLedgerEntry[]>();
  for (const e of entries) {
    const key = e.job_id ?? "unknown";
    const list = byJob.get(key);
    if (list) list.push(e);
    else byJob.set(key, [e]);
  }

  const groups: JobBreakdown[] = [];
  for (const [jobId, rows] of byJob) {
    const providerPaid = sum(rows, (e) => e.account === "provider" && e.reason === "settle");
    const protocolFee = sum(rows, (e) => e.account === "protocol" && e.reason === "settle");
    const dataCost = sum(rows, (e) => e.reason === "data_cost" && e.direction === "debit");
    const escrowed = sum(rows, (e) => e.reason === "escrow_hold" && e.direction === "debit");
    const refunded = sum(rows, (e) => e.reason === "refund" && e.direction === "credit");
    const latestAt = rows.reduce(
      (m, e) => (e.created_at > m ? e.created_at : m),
      rows[0]!.created_at,
    );
    groups.push({
      jobId,
      entries: rows,
      escrowed,
      providerPaid,
      protocolFee,
      dataCost,
      refunded,
      totalCharged: providerPaid + protocolFee + dataCost,
      latestAt,
    });
  }
  groups.sort((a, b) => (a.latestAt < b.latestAt ? 1 : -1));
  return groups;
}

/** Serialise ledger legs to CSV for spreadsheet/accounting import (Session 10.4). */
export function toCsv(entries: BillingLedgerEntry[]): string {
  const header = [
    "created_at",
    "job_id",
    "entry_group",
    "account",
    "direction",
    "amount",
    "reason",
  ];
  const escape = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  const lines = entries.map((e) =>
    [
      e.created_at,
      e.job_id ?? "",
      e.entry_group,
      e.account,
      e.direction,
      e.amount.toFixed(6),
      e.reason,
    ]
      .map((v) => escape(String(v)))
      .join(","),
  );
  return [header.join(","), ...lines].join("\n");
}
