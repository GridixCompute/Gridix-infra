"use client";

import { useState } from "react";
import Link from "next/link";
import { Card, CardBody, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { Timestamp } from "@/components/domain/Timestamp";
import { useBillingLedger } from "@/lib/hooks/useBilling";
import { groupByJob, toCsv, type JobBreakdown } from "@/lib/billing/ledger";
import type { BillingLedgerEntry } from "@/lib/api/types";

/**
 * Per-job ledger with the escrow-hold → charge → refund story and an exact cost
 * breakdown (Session 10.1/10.2). Every group's legs are one click away so the
 * double entry is auditable. Export to CSV for accounting (Session 10.4).
 */
export function LedgerHistory() {
  const { data: entries, isLoading, isError, refetch } = useBillingLedger(200);

  function exportCsv() {
    if (!entries || entries.length === 0) return;
    const blob = new Blob([toCsv(entries)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "gridix-ledger.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <Card>
      <CardBody className="space-y-4">
        <div className="flex items-center justify-between">
          <CardTitle className="!mt-0">Ledger</CardTitle>
          <Button
            variant="secondary"
            size="sm"
            onClick={exportCsv}
            disabled={!entries || entries.length === 0}
          >
            Export CSV
          </Button>
        </div>

        {isLoading ? (
          <Skeleton className="h-40" />
        ) : isError ? (
          <ErrorState message="Couldn't load your ledger." onRetry={() => void refetch()} />
        ) : entries && entries.length > 0 ? (
          <div className="space-y-2">
            {groupByJob(entries).map((g) => (
              <JobGroup key={g.jobId} group={g} />
            ))}
          </div>
        ) : (
          <EmptyState
            title="No charges yet"
            description="Once you run jobs, every escrow hold, charge and refund shows up here — down to the individual ledger entry."
          />
        )}
      </CardBody>
    </Card>
  );
}

function JobGroup({ group }: { group: JobBreakdown }) {
  const [open, setOpen] = useState(false);
  const refunded = group.refunded > 0;

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-hairline)] bg-[var(--color-panel)]">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <Link
            href={`/jobs/${group.jobId}`}
            className="text-sm font-[var(--font-mono)] text-[var(--color-signal-bright)] hover:underline"
          >
            {group.jobId.slice(0, 8)}…
          </Link>
          <div className="mt-0.5 text-xs text-[var(--color-ink-faint)]">
            <Timestamp iso={group.latestAt} />
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className="text-xs text-[var(--color-ink-faint)]">Charged</div>
            <USDCAmount amount={group.totalCharged} />
          </div>
          {refunded && (
            <Badge tone="neutral">
              <USDCAmount amount={group.refunded} tone="credit" symbol={false} /> refunded
            </Badge>
          )}
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="text-sm text-[var(--color-signal-bright)] hover:underline"
          >
            {open ? "Hide" : "Details"}
          </button>
        </div>
      </div>

      {open && (
        <div className="space-y-3 border-t border-[var(--color-hairline)] px-4 py-3">
          {/* Breakdown — sums exactly to Charged. */}
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
            <Break label="Provider" value={group.providerPaid} />
            <Break label="Protocol fee" value={group.protocolFee} />
            <Break label="Data" value={group.dataCost} />
            <Break label="Escrow held" value={group.escrowed} muted />
          </dl>

          {/* Raw double-entry legs. */}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-[var(--color-ink-faint)] uppercase">
                  <th className="py-1 pr-4 font-medium">Reason</th>
                  <th className="py-1 pr-4 font-medium">Account</th>
                  <th className="py-1 pr-4 font-medium">Debit</th>
                  <th className="py-1 pr-4 font-medium">Credit</th>
                  <th className="py-1 font-medium">When</th>
                </tr>
              </thead>
              <tbody className="font-[var(--font-mono)]">
                {group.entries.map((e) => (
                  <LegRow key={e.id} entry={e} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function Break({ label, value, muted }: { label: string; value: number; muted?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-[var(--color-ink-faint)]">{label}</dt>
      <dd className={muted ? "text-[var(--color-ink-faint)]" : "text-[var(--color-ink)]"}>
        <USDCAmount amount={value} tone={muted ? "muted" : "default"} />
      </dd>
    </div>
  );
}

function LegRow({ entry }: { entry: BillingLedgerEntry }) {
  const isDebit = entry.direction === "debit";
  return (
    <tr className="border-t border-[var(--color-hairline)]">
      <td className="py-1 pr-4 text-[var(--color-ink-soft)]">{entry.reason}</td>
      <td className="py-1 pr-4 text-[var(--color-ink-faint)]">{entry.account}</td>
      <td className="py-1 pr-4 text-[var(--color-ink)]">
        {isDebit ? <USDCAmount amount={entry.amount} /> : ""}
      </td>
      <td className="py-1 pr-4 text-[var(--color-success)]">
        {!isDebit ? <USDCAmount amount={entry.amount} tone="credit" /> : ""}
      </td>
      <td className="py-1 text-[var(--color-ink-faint)]">
        <Timestamp iso={entry.created_at} />
      </td>
    </tr>
  );
}
