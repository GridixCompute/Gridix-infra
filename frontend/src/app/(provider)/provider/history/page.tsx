"use client";

import { Card, CardBody, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { ProviderStat } from "@/components/provider/ProviderStat";
import { Timestamp } from "@/components/domain/Timestamp";
import { formatDuration } from "@/lib/format/time";
import { useProviderMe, useProviderJobs, useProviderReputation } from "@/lib/hooks/useProvider";
import type { ProviderJobAttempt, ReputationEvent } from "@/lib/api/types";

const OUTCOME: Record<string, "success" | "danger" | "warning" | "neutral" | "info"> = {
  completed: "success",
  failed: "danger",
  timeout: "danger",
  reassigned: "warning",
  running: "info",
  assigned: "neutral",
};

export default function HistoryPage() {
  const { data: provider } = useProviderMe();
  const jobs = useProviderJobs(50);
  const reputation = useProviderReputation(50);

  const completed = jobs.data?.filter((j) => j.outcome === "completed").length ?? 0;
  const failed =
    jobs.data?.filter((j) => j.outcome === "failed" || j.outcome === "timeout").length ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
          History
        </h1>
        <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
          Every job your node ran and every move in your reputation.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <ProviderStat
          label="Reputation"
          value={provider ? provider.reputation.toFixed(1) : "—"}
          hint="of 100"
        />
        <ProviderStat label="Completed" value={completed} hint="attempts" />
        <ProviderStat label="Failed / timed out" value={failed} hint="attempts" />
      </div>

      {/* Reputation timeline */}
      <Card>
        <CardBody className="space-y-3">
          <CardTitle className="!mt-0">Reputation events</CardTitle>
          {reputation.isLoading ? (
            <Skeleton className="h-24" />
          ) : reputation.isError ? (
            <ErrorState
              message="Couldn't load reputation events."
              onRetry={() => void reputation.refetch()}
            />
          ) : reputation.data && reputation.data.length > 0 ? (
            <ul className="space-y-2">
              {reputation.data.map((e) => (
                <ReputationRow key={e.id} event={e} />
              ))}
            </ul>
          ) : (
            <p className="text-sm text-[var(--color-ink-faint)]">
              No reputation events yet. They accrue as you complete (or fail) jobs.
            </p>
          )}
        </CardBody>
      </Card>

      {/* Job history */}
      <Card>
        <CardBody className="space-y-3">
          <CardTitle className="!mt-0">Job history</CardTitle>
          {jobs.isLoading ? (
            <Skeleton className="h-40" />
          ) : jobs.isError ? (
            <ErrorState message="Couldn't load job history." onRetry={() => void jobs.refetch()} />
          ) : jobs.data && jobs.data.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="text-xs tracking-wide text-[var(--color-ink-faint)] uppercase">
                    <th className="py-2 pr-4 font-medium">Job</th>
                    <th className="py-2 pr-4 font-medium">Outcome</th>
                    <th className="py-2 pr-4 font-medium">Duration</th>
                    <th className="py-2 pr-4 font-medium">Kind</th>
                    <th className="py-2 font-medium">When</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.data.map((j) => (
                    <JobRow key={j.attempt_id} attempt={j} />
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              title="No jobs yet"
              description="Once your agent is online and staked, jobs the scheduler assigns to you will appear here."
            />
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function ReputationRow({ event }: { event: ReputationEvent }) {
  const positive = event.delta >= 0;
  return (
    <li className="flex items-center justify-between border-t border-[var(--color-hairline)] py-2 first:border-t-0">
      <div>
        <span className="text-sm text-[var(--color-ink)]">{event.kind.replace(/_/g, " ")}</span>
        <span className="ml-2 text-xs text-[var(--color-ink-faint)]">
          <Timestamp iso={event.created_at} />
        </span>
      </div>
      <div className="flex items-center gap-3">
        <span
          className={`text-sm font-[var(--font-mono)] ${
            positive ? "text-[var(--color-success)]" : "text-[var(--color-danger)]"
          }`}
        >
          {positive ? "+" : ""}
          {event.delta.toFixed(1)}
        </span>
        <span className="w-12 text-right text-sm font-[var(--font-mono)] text-[var(--color-ink-faint)]">
          {event.score_after.toFixed(1)}
        </span>
      </div>
    </li>
  );
}

function JobRow({ attempt }: { attempt: ProviderJobAttempt }) {
  const tone = OUTCOME[attempt.outcome] ?? "neutral";
  const duration =
    attempt.started_at && attempt.finished_at
      ? formatDuration(attempt.started_at, attempt.finished_at)
      : "—";
  return (
    <tr className="border-t border-[var(--color-hairline)]">
      <td className="py-2 pr-4">
        <span className="text-xs font-[var(--font-mono)] text-[var(--color-ink-soft)]">
          {attempt.image_ref}
        </span>
      </td>
      <td className="py-2 pr-4">
        <Badge tone={tone}>{attempt.outcome}</Badge>
      </td>
      <td className="py-2 pr-4 font-[var(--font-mono)] text-[var(--color-ink)]">{duration}</td>
      <td className="py-2 pr-4">
        {attempt.is_high_value ? (
          <span className="text-xs text-[var(--color-ink-soft)]">quorum ×{attempt.redundancy}</span>
        ) : (
          <span className="text-xs text-[var(--color-ink-faint)]">standard</span>
        )}
      </td>
      <td className="py-2 text-xs text-[var(--color-ink-faint)]">
        <Timestamp iso={attempt.created_at} />
      </td>
    </tr>
  );
}
