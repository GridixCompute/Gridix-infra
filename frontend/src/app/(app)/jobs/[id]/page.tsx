"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useJob, useJobAudit } from "@/lib/hooks/useJob";
import { JobStatusBadge } from "@/components/domain/JobStatusBadge";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { Timestamp } from "@/components/domain/Timestamp";
import { AddressDisplay } from "@/components/domain/AddressDisplay";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/States";
import { isApiError } from "@/lib/api/errors";
import { formatDuration } from "@/lib/format/time";
import { isTerminal } from "@/lib/api/types";
import type { AttemptRecord, LedgerRecord, Job } from "@/lib/api/types";

export default function JobDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: job, isLoading, isError, error, refetch } = useJob(id);
  const { data: audit } = useJobAudit(id, !!job && isTerminal(job.status));

  if (isLoading) return <DetailSkeleton />;
  if (isError || !job) {
    return (
      <Card>
        <ErrorState
          title="Couldn't load this job"
          message={isApiError(error) ? error.message : "Try again."}
          onRetry={() => void refetch()}
        />
      </Card>
    );
  }

  const attempts = audit?.attempts ?? [];
  const ledger = audit?.ledger ?? [];
  const reassigned = attempts.length > 1;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <Link
          href="/jobs"
          className="text-sm text-[var(--color-ink-faint)] hover:text-[var(--color-ink)]"
        >
          ← Jobs
        </Link>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <JobStatusBadge status={job.status} />
            <h1 className="text-lg font-[var(--font-mono)] text-[var(--color-ink)]">
              {job.image_ref}
            </h1>
          </div>
          <ResultButton jobId={job.id} available={job.status === "completed" && !!job.result_ref} />
        </div>
        <p className="mt-2 flex items-center gap-2 text-sm text-[var(--color-ink-faint)]">
          Job <AddressDisplay value={job.id} lead={10} tail={6} /> · submitted{" "}
          <Timestamp iso={job.created_at} />
        </p>
      </div>

      {(job.status === "failed" || job.status === "timeout") && (
        <FailureBanner status={job.status} ledger={ledger} />
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Escrow held">
          {job.escrow_amount != null ? <USDCAmount amount={job.escrow_amount} /> : "—"}
        </Stat>
        <Stat label="Final cost">
          {job.cost_final != null ? (
            <USDCAmount amount={job.cost_final} tone="signal" />
          ) : (
            <span className="text-[var(--color-ink-faint)]">pending settlement</span>
          )}
        </Stat>
        <Stat label={reassigned ? `Attempts (${attempts.length})` : "Attempts"}>
          <span className={reassigned ? "text-[var(--color-warning)]" : undefined}>
            {attempts.length || (job.attempt_count ?? 0)}
            {reassigned && " · reassigned"}
          </span>
        </Stat>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Timeline</CardTitle>
          </CardHeader>
          <CardBody>
            <Timeline job={job} attempts={attempts} />
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Configuration</CardTitle>
          </CardHeader>
          <CardBody className="space-y-2 text-sm">
            <Config label="Timeout" value={`${job.timeout_seconds}s`} />
            <Config label="Redundancy (K)" value={String(job.redundancy)} />
            <Config label="High value" value={job.is_high_value ? "yes" : "no"} />
            <Config label="Network egress" value={job.allow_egress ? "allowed" : "blocked"} />
            <Config label="Data tier" value={job.data_tier} />
            {job.assigned_provider_id && (
              <Config
                label="Provider"
                value={<AddressDisplay value={job.assigned_provider_id} lead={8} tail={4} />}
              />
            )}
          </CardBody>
        </Card>
      </div>

      {job.redundancy > 1 && attempts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Quorum results (K={job.redundancy})</CardTitle>
          </CardHeader>
          <CardBody>
            <AttemptsTable attempts={attempts} />
          </CardBody>
        </Card>
      )}

      {ledger.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Money movements</CardTitle>
          </CardHeader>
          <CardBody>
            <LedgerTable ledger={ledger} />
          </CardBody>
        </Card>
      )}
    </div>
  );
}

function Timeline({ job, attempts }: { job: Job; attempts: AttemptRecord[] }) {
  type Node = {
    label: string;
    time?: string | null;
    tone?: "signal" | "danger" | "muted";
    note?: string;
  };
  const nodes: Node[] = [{ label: "Queued", time: job.created_at, tone: "muted" }];

  for (const a of attempts) {
    const label = attempts.length > 1 ? `Attempt ${a.attempt_number}` : "Execution";
    if (a.started_at) nodes.push({ label: `${label} started`, time: a.started_at, tone: "signal" });
    if (a.finished_at)
      nodes.push({
        label: `${label} ${a.outcome}`,
        time: a.finished_at,
        tone: a.outcome === "completed" ? "signal" : "danger",
        note: a.provider_id ? `provider ${a.provider_id.slice(0, 8)}…` : undefined,
      });
  }
  if (attempts.length === 0 && !isTerminal(job.status)) {
    nodes.push({ label: "Waiting for a provider", tone: "muted" });
  }

  return (
    <ol className="space-y-4">
      {nodes.map((n, i) => (
        <li key={i} className="flex gap-3">
          <div className="flex flex-col items-center">
            <span
              className="mt-1 h-2.5 w-2.5 rounded-full"
              style={{
                backgroundColor:
                  n.tone === "danger"
                    ? "var(--color-danger)"
                    : n.tone === "signal"
                      ? "var(--color-signal)"
                      : "var(--color-ink-disabled)",
              }}
            />
            {i < nodes.length - 1 && <span className="w-px flex-1 bg-[var(--color-hairline)]" />}
          </div>
          <div className="pb-1">
            <div className="text-sm text-[var(--color-ink)]">{n.label}</div>
            {n.time && <Timestamp iso={n.time} className="text-xs" />}
            {n.note && <div className="text-xs text-[var(--color-ink-faint)]">{n.note}</div>}
          </div>
        </li>
      ))}
    </ol>
  );
}

function FailureBanner({
  status,
  ledger,
}: {
  status: "failed" | "timeout";
  ledger: LedgerRecord[];
}) {
  const refund = ledger.find((l) => l.reason.toLowerCase().includes("refund"));
  return (
    <div className="rounded-[var(--radius-md)] border border-[#ffab3d55] bg-[#ffab3d1a] p-4">
      <div className="text-sm font-[var(--font-display)] font-semibold text-[var(--color-warning)]">
        {status === "timeout" ? "Job timed out" : "Job failed"}
      </div>
      <p className="mt-1 text-sm text-[var(--color-ink-soft)]">
        {status === "timeout"
          ? "The container exceeded its timeout and was stopped."
          : "The container exited with an error or failed verification."}{" "}
        {refund ? (
          <>
            Your escrow was refunded (<USDCAmount amount={refund.amount} tone="credit" />
            ).
          </>
        ) : (
          "Unused escrow is refunded to your balance."
        )}
      </p>
    </div>
  );
}

function AttemptsTable({ attempts }: { attempts: AttemptRecord[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--color-hairline)] text-left text-xs text-[var(--color-ink-faint)] uppercase">
            <th className="py-2 pr-4 font-medium">#</th>
            <th className="py-2 pr-4 font-medium">Provider</th>
            <th className="py-2 pr-4 font-medium">Outcome</th>
            <th className="py-2 font-medium">Duration</th>
          </tr>
        </thead>
        <tbody>
          {attempts.map((a) => (
            <tr
              key={a.attempt_number}
              className="border-b border-[var(--color-hairline)] last:border-0"
            >
              <td className="py-2 pr-4 font-[var(--font-mono)]">{a.attempt_number}</td>
              <td className="py-2 pr-4 font-[var(--font-mono)] text-[var(--color-ink-soft)]">
                {a.provider_id ? `${a.provider_id.slice(0, 10)}…` : "—"}
              </td>
              <td className="py-2 pr-4">
                <span
                  className={
                    a.outcome === "completed"
                      ? "text-[var(--color-success)]"
                      : a.outcome === "reassigned"
                        ? "text-[var(--color-warning)]"
                        : "text-[var(--color-danger)]"
                  }
                >
                  {a.outcome}
                </span>
              </td>
              <td className="py-2 font-[var(--font-mono)] text-[var(--color-ink-soft)]">
                {a.started_at && a.finished_at ? formatDuration(a.started_at, a.finished_at) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LedgerTable({ ledger }: { ledger: LedgerRecord[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <tbody>
          {ledger.map((l, i) => (
            <tr key={i} className="border-b border-[var(--color-hairline)] last:border-0">
              <td className="py-2 pr-4 text-[var(--color-ink-soft)]">{l.reason}</td>
              <td className="py-2 pr-4 text-xs text-[var(--color-ink-faint)] uppercase">
                {l.direction}
              </td>
              <td className="py-2 text-right">
                <USDCAmount
                  amount={l.amount}
                  tone={l.direction.toLowerCase() === "credit" ? "credit" : "default"}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResultButton({ jobId, available }: { jobId: string; available: boolean }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function download() {
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(`/api/gw/jobs/${jobId}/result`, { credentials: "same-origin" });
      if (!res.ok) {
        setErr(res.status === 409 ? "No result yet." : "Download failed.");
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const dispo = res.headers.get("content-disposition");
      const match = dispo?.match(/filename="?([^"]+)"?/);
      a.download = match?.[1] ?? `gridix-result-${jobId.slice(0, 8)}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      setErr("Download failed.");
    } finally {
      setBusy(false);
    }
  }

  if (!available) {
    return (
      <Button variant="secondary" disabled title="Result is available once the job completes.">
        Download result
      </Button>
    );
  }
  return (
    <div className="text-right">
      <Button onClick={download} loading={busy}>
        Download result
      </Button>
      {err && <p className="mt-1 text-xs text-[var(--color-danger)]">{err}</p>}
    </div>
  );
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardBody>
        <div className="text-xs tracking-wide text-[var(--color-ink-faint)] uppercase">{label}</div>
        <div className="mt-1 text-lg">{children}</div>
      </CardBody>
    </Card>
  );
}

function Config({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[var(--color-ink-faint)]">{label}</span>
      <span className="text-[var(--color-ink)]">{value}</span>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Skeleton className="h-8 w-64" />
      <div className="grid gap-4 sm:grid-cols-3">
        <Skeleton className="h-20" />
        <Skeleton className="h-20" />
        <Skeleton className="h-20" />
      </div>
      <Skeleton className="h-64" />
    </div>
  );
}
