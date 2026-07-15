"use client";

import Link from "next/link";
import { Card, CardBody, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/States";
import { ProviderStat } from "@/components/provider/ProviderStat";
import { Timestamp } from "@/components/domain/Timestamp";
import { useProviderMe, useProviderTrust } from "@/lib/hooks/useProvider";
import { agentConnection } from "@/lib/provider/connection";

const TRUST_LABEL: Record<string, string> = {
  attested: "TEE-attested",
  benchmark: "Benchmarked",
  self_report: "Self-reported",
};

export default function ProviderOverviewPage() {
  const { data: provider, isLoading, isError, refetch } = useProviderMe();
  const { data: trust } = useProviderTrust();

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-40" />
      </div>
    );
  }

  if (isError || !provider) {
    return (
      <ErrorState
        message="Couldn't load your provider. Check your connection and try again."
        onRetry={() => void refetch()}
      />
    );
  }

  const conn = agentConnection(provider);
  const trustSource = trust?.trust_source ?? "self_report";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
            {provider.name}
          </h1>
          <p className="mt-1 flex items-center gap-2 text-sm text-[var(--color-ink-faint)]">
            <span
              className={`h-2 w-2 rounded-full ${
                conn.online ? "bg-[var(--color-success)]" : "bg-[var(--color-ink-disabled)]"
              }`}
              aria-hidden="true"
            />
            {conn.label}
            {provider.last_seen && (
              <>
                {" · last seen "}
                <Timestamp iso={provider.last_seen} />
              </>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {provider.degraded && <Badge tone="warning">Degraded</Badge>}
          {!provider.enabled && <Badge tone="danger">Disabled</Badge>}
          {provider.enabled && !provider.degraded && conn.online && (
            <Badge tone="success">Serving</Badge>
          )}
        </div>
      </div>

      {!conn.everConnected && (
        <Card className="border-[var(--color-signal-dim)] bg-[var(--color-signal-glow)]">
          <CardBody className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <CardTitle>Your agent hasn&apos;t connected yet</CardTitle>
              <p className="mt-1 text-sm text-[var(--color-ink-soft)]">
                Install the GRIDIX agent on your node to start receiving jobs.
              </p>
            </div>
            <Link href="/provider/onboarding">
              <Button>Set up your agent</Button>
            </Link>
          </CardBody>
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <ProviderStat label="Reputation" value={provider.reputation.toFixed(1)} hint="of 100" />
        <ProviderStat
          label="Trust"
          value={TRUST_LABEL[trustSource] ?? trustSource}
          hint={trust?.attested ? "hardware attested" : "raise it by benchmarking"}
        />
        <ProviderStat label="Region" value={provider.region ?? "—"} />
        <ProviderStat label="Max concurrent" value={provider.max_concurrent} hint="jobs at once" />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardBody className="space-y-3">
            <CardTitle>Declared hardware</CardTitle>
            <dl className="space-y-2 text-sm">
              <Row label="GPU" value={provider.gpu_model ?? "None declared"} />
              <Row
                label="GPU VRAM"
                value={
                  provider.gpu_vram_mb ? `${(provider.gpu_vram_mb / 1024).toFixed(0)} GB` : "—"
                }
              />
              <Row label="CPU cores" value={String(provider.cpu_cores)} />
              <Row label="Memory" value={`${(provider.memory_mb / 1024).toFixed(1)} GB`} />
            </dl>
            <Link
              href="/provider/hardware"
              className="inline-block text-sm text-[var(--color-signal-bright)] hover:underline"
            >
              Manage hardware & benchmark →
            </Link>
          </CardBody>
        </Card>

        <Card>
          <CardBody className="space-y-3">
            <CardTitle>Next steps</CardTitle>
            <ul className="space-y-2 text-sm text-[var(--color-ink-soft)]">
              <QuickLink href="/provider/earnings" label="Stake & withdraw earnings" />
              <QuickLink href="/provider/history" label="Job & reputation history" />
              <QuickLink href="/provider/disputes" label="Review slashes & appeal" />
              <QuickLink href="/provider/onboarding" label="Agent setup & health" />
            </ul>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-[var(--color-ink-faint)]">{label}</dt>
      <dd className="font-[var(--font-mono)] text-[var(--color-ink)]">{value}</dd>
    </div>
  );
}

function QuickLink({ href, label }: { href: string; label: string }) {
  return (
    <li>
      <Link href={href} className="text-[var(--color-signal-bright)] hover:underline">
        {label} →
      </Link>
    </li>
  );
}
