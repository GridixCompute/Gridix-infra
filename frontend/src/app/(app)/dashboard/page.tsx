"use client";

import Link from "next/link";
import { useJobs } from "@/lib/hooks/useJobs";
import { JobStatusBadge } from "@/components/domain/JobStatusBadge";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { Timestamp } from "@/components/domain/Timestamp";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { isApiError } from "@/lib/api/errors";
import { isTerminal } from "@/lib/api/types";

export default function DashboardPage() {
  const { data: jobs, isLoading, isError, error, refetch, isFetching } = useJobs({ limit: 50 });

  const active = jobs?.filter((j) => !isTerminal(j.status)).length ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="font-[var(--font-display)] text-2xl font-bold text-[var(--color-ink)]">
            Jobs
          </h1>
          <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
            {active > 0
              ? `${active} active · updating live`
              : "Everything you've run on the network."}
          </p>
        </div>
        <Link href="/jobs/new">
          <Button>New job</Button>
        </Link>
      </div>

      <Card>
        {isLoading ? (
          <LoadingRows />
        ) : isError ? (
          <ErrorState
            message={isApiError(error) ? error.message : "Couldn't load your jobs."}
            onRetry={() => void refetch()}
          />
        ) : !jobs || jobs.length === 0 ? (
          <EmptyState
            title="No jobs yet"
            description="Submit a container to run on the GRIDIX network. You'll see it move through queued → running → completed here, live."
            action={{ label: "Submit your first job", href: "/jobs/new" }}
          />
        ) : (
          <JobsTable jobs={jobs} loading={isFetching} />
        )}
      </Card>
    </div>
  );
}

function JobsTable({ jobs, loading }: { jobs: NonNullable<ReturnType<typeof useJobs>["data"]>; loading: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--color-hairline)] text-left text-xs uppercase tracking-wide text-[var(--color-ink-faint)]">
            <th className="px-5 py-3 font-medium">Status</th>
            <th className="px-5 py-3 font-medium">Image</th>
            <th className="px-5 py-3 font-medium">Submitted</th>
            <th className="px-5 py-3 text-right font-medium">Cost</th>
            <th className="px-5 py-3" aria-label="actions" />
          </tr>
        </thead>
        <tbody className={loading ? "opacity-70 transition-opacity" : ""}>
          {jobs.map((job) => (
            <tr
              key={job.id}
              className="border-b border-[var(--color-hairline)] last:border-0 hover:bg-[var(--color-panel-raised)]/40"
            >
              <td className="px-5 py-3">
                <JobStatusBadge status={job.status} />
              </td>
              <td className="max-w-xs truncate px-5 py-3 font-[var(--font-mono)] text-[var(--color-ink-soft)]">
                {job.image_ref}
              </td>
              <td className="px-5 py-3">
                <Timestamp iso={job.created_at} />
              </td>
              <td className="px-5 py-3 text-right">
                {job.cost_final != null ? (
                  <USDCAmount amount={job.cost_final} />
                ) : job.escrow_amount != null ? (
                  <span className="text-[var(--color-ink-faint)]">
                    <USDCAmount amount={job.escrow_amount} tone="muted" symbol={false} /> held
                  </span>
                ) : (
                  <span className="text-[var(--color-ink-disabled)]">—</span>
                )}
              </td>
              <td className="px-5 py-3 text-right">
                <Link
                  href={`/jobs/${job.id}`}
                  className="text-[var(--color-signal-bright)] hover:underline"
                >
                  View
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LoadingRows() {
  return (
    <div className="space-y-3 p-5">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="flex items-center gap-4">
          <Skeleton className="h-6 w-24" />
          <Skeleton className="h-5 flex-1" />
          <Skeleton className="h-5 w-20" />
        </div>
      ))}
    </div>
  );
}
