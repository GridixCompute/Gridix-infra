"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useJobs } from "@/lib/hooks/useJobs";
import { JobsList } from "@/components/app/JobsList";
import { Button } from "@/components/ui/Button";
import { isTerminal } from "@/lib/api/types";

// First-run only, and it reads on-chain escrow — keep its wallet code off the
// hot dashboard bundle for returning users (Session 13.4 / 14.2).
const GettingStarted = dynamic(
  () => import("@/components/app/GettingStarted").then((m) => m.GettingStarted),
  { ssr: false },
);

export default function DashboardPage() {
  const { data: jobs } = useJobs({ limit: 50 });
  const active = jobs?.filter((j) => !isTerminal(j.status)).length ?? 0;
  // First run: the developer is loaded but has never submitted a job.
  const firstRun = jobs?.length === 0;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
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
      {firstRun && <GettingStarted />}
      <JobsList />
    </div>
  );
}
