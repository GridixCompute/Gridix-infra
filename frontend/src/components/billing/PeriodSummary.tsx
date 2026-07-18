"use client";

import type { ReactNode } from "react";
import { Card, CardBody } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/States";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { useBillingSummary } from "@/lib/hooks/useBilling";

/**
 * Period totals from the backend ledger (Session 10.3). Every figure is the
 * backend's — the UI only lays them out. `total_spent` breaks down exactly into
 * provider payments, protocol fees and data charges.
 */
export function PeriodSummary() {
  const { data, isLoading, isError, refetch } = useBillingSummary();

  if (isLoading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
    );
  }
  if (isError || !data) {
    return (
      <ErrorState message="Couldn't load your billing summary." onRetry={() => void refetch()} />
    );
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          label="Total spent"
          value={<USDCAmount amount={data.total_spent} />}
          hint={`across ${data.job_count} ${data.job_count === 1 ? "job" : "jobs"}`}
        />
        <Tile label="Provider payments" value={<USDCAmount amount={data.provider_paid} />} />
        <Tile label="Protocol fees" value={<USDCAmount amount={data.protocol_fees} />} />
        <Tile
          label="Data charges"
          value={<USDCAmount amount={data.data_costs} />}
          hint="egress / movement"
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          label="Refunded"
          value={<USDCAmount amount={data.total_refunded} tone="credit" />}
          hint="unused escrow returned"
        />
        <Tile
          label="Held now"
          value={<USDCAmount amount={data.total_held} />}
          hint="locked by active jobs"
        />
        <Tile
          label="Escrowed lifetime"
          value={<USDCAmount amount={data.total_escrowed} />}
          hint="total ever held"
        />
      </div>
    </div>
  );
}

function Tile({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <Card>
      <CardBody>
        <div className="text-xs tracking-wide text-[var(--color-ink-faint)] uppercase">{label}</div>
        <div className="mt-1.5 text-xl">{value}</div>
        {hint && <p className="mt-1 text-xs text-[var(--color-ink-faint)]">{hint}</p>}
      </CardBody>
    </Card>
  );
}
