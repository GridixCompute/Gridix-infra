"use client";

import Link from "next/link";
import { JobsList } from "@/components/app/JobsList";
import { Button } from "@/components/ui/Button";

export default function JobsPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
            All jobs
          </h1>
          <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
            Everything you&apos;ve run on the network.
          </p>
        </div>
        <Link href="/jobs/new">
          <Button>New job</Button>
        </Link>
      </div>
      <JobsList />
    </div>
  );
}
