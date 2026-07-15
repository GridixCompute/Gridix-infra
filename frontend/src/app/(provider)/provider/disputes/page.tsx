"use client";

import { useState } from "react";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState, EmptyState } from "@/components/ui/States";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { Timestamp } from "@/components/domain/Timestamp";
import { AddressDisplay } from "@/components/domain/AddressDisplay";
import { useProviderDisputes, useContestDispute } from "@/lib/hooks/useProvider";
import { isApiError } from "@/lib/api/errors";
import type { DisputeResponse } from "@/lib/api/types";

const STATE: Record<string, { label: string; tone: "warning" | "info" | "danger" | "success" }> = {
  open: { label: "Open — contestable", tone: "warning" },
  under_review: { label: "Under review", tone: "info" },
  upheld: { label: "Upheld — stake slashed", tone: "danger" },
  overturned: { label: "Overturned — stake returned", tone: "success" },
};

export default function DisputesPage() {
  const { data: disputes, isLoading, isError, refetch } = useProviderDisputes();

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
      </div>
    );
  }
  if (isError || !disputes) {
    return (
      <ErrorState
        message="Couldn't load your disputes. Try again."
        onRetry={() => void refetch()}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
          Slashes & disputes
        </h1>
        <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
          Every slash links the evidence that triggered it. Contest an open one to send it to
          review.
        </p>
      </div>

      {disputes.length === 0 ? (
        <EmptyState
          title="No slashes"
          description="Your stake has never been slashed. Keep completing jobs honestly and it stays that way."
        />
      ) : (
        <div className="space-y-4">
          {disputes.map((d) => (
            <DisputeCard key={d.id} dispute={d} />
          ))}
        </div>
      )}
    </div>
  );
}

function DisputeCard({ dispute }: { dispute: DisputeResponse }) {
  const contest = useContestDispute();
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const state = STATE[dispute.state] ?? { label: dispute.state, tone: "info" as const };
  const evidenceEntries = Object.entries(dispute.evidence ?? {});

  async function onContest() {
    setError(null);
    try {
      await contest.mutateAsync(dispute.id);
    } catch (err) {
      setError(isApiError(err) ? err.message : "Couldn't submit your contest. Try again.");
    }
  }

  return (
    <Card>
      <CardBody className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg font-[var(--font-display)] font-semibold text-[var(--color-ink)]">
                <USDCAmount amount={dispute.amount} />
              </span>
              <Badge tone={state.tone}>{state.label}</Badge>
            </div>
            <p className="mt-1 text-sm text-[var(--color-ink-soft)]">
              Reason: <span className="text-[var(--color-ink)]">{dispute.reason}</span>
            </p>
            <p className="mt-0.5 text-xs text-[var(--color-ink-faint)]">
              Opened <Timestamp iso={dispute.created_at} />
              {dispute.resolved_at && (
                <>
                  {" · resolved "}
                  <Timestamp iso={dispute.resolved_at} />
                </>
              )}
            </p>
          </div>
          {dispute.state === "open" && (
            <Button size="sm" onClick={onContest} loading={contest.isPending}>
              Contest slash
            </Button>
          )}
        </div>

        {dispute.ruling_reason && (
          <p className="rounded-[var(--radius-sm)] border border-[var(--color-hairline)] bg-[var(--color-panel)] px-3 py-2 text-sm text-[var(--color-ink-soft)]">
            <span className="text-[var(--color-ink-faint)]">Ruling: </span>
            {dispute.ruling_reason}
          </p>
        )}

        {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}

        {(evidenceEntries.length > 0 || dispute.evidence_hash) && (
          <div>
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="text-sm text-[var(--color-signal-bright)] hover:underline"
            >
              {open ? "Hide evidence" : "View evidence"}
            </button>
            {open && (
              <div className="mt-2 space-y-2 rounded-[var(--radius-sm)] border border-[var(--color-hairline)] bg-[var(--color-void)] p-3">
                {dispute.evidence_hash && (
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-[var(--color-ink-faint)]">Evidence hash</span>
                    <code className="font-[var(--font-mono)] break-all text-[var(--color-ink-soft)]">
                      {dispute.evidence_hash}
                    </code>
                  </div>
                )}
                {dispute.job_id && (
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-[var(--color-ink-faint)]">Job</span>
                    <code className="font-[var(--font-mono)] text-[var(--color-ink-soft)]">
                      {dispute.job_id}
                    </code>
                  </div>
                )}
                <table className="w-full text-left text-sm">
                  <tbody>
                    {evidenceEntries.map(([k, v]) => (
                      <tr key={k} className="border-t border-[var(--color-hairline)]">
                        <td className="py-1.5 pr-4 align-top text-[var(--color-ink-faint)]">{k}</td>
                        <td className="py-1.5 font-[var(--font-mono)] break-all text-[var(--color-ink)]">
                          {typeof v === "string" && /^0x[0-9a-fA-F]{40}$/.test(v) ? (
                            <AddressDisplay value={v} />
                          ) : typeof v === "object" ? (
                            JSON.stringify(v)
                          ) : (
                            String(v)
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  );
}
