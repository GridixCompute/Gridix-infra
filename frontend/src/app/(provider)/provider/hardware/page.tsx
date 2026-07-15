"use client";

import { useState } from "react";
import { Card, CardBody, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/States";
import { ProviderStat } from "@/components/provider/ProviderStat";
import { CapabilitiesForm } from "@/components/provider/CapabilitiesForm";
import { Timestamp } from "@/components/domain/Timestamp";
import { formatBytes } from "@/lib/format/bytes";
import {
  useProviderMe,
  useProviderBenchmark,
  useProviderTrust,
  useProviderBandwidth,
} from "@/lib/hooks/useProvider";

const TRUST: Record<
  string,
  { label: string; tone: "success" | "info" | "neutral"; blurb: string }
> = {
  attested: {
    label: "TEE-attested",
    tone: "success",
    blurb: "Your hardware is verified by a trusted execution environment — the strongest tier.",
  },
  benchmark: {
    label: "Benchmarked",
    tone: "info",
    blurb: "A signed benchmark measured your GPU. Jobs trust your declared throughput.",
  },
  self_report: {
    label: "Self-reported",
    tone: "neutral",
    blurb: "Nothing has measured your hardware yet. Run the agent benchmark to raise trust.",
  },
};

export default function HardwarePage() {
  const { data: provider, isLoading, isError, refetch } = useProviderMe();
  const { data: benchmark } = useProviderBenchmark();
  const { data: trust } = useProviderTrust();
  const { data: bandwidth } = useProviderBandwidth();
  const [editing, setEditing] = useState(false);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-48" />
        <Skeleton className="h-40" />
      </div>
    );
  }
  if (isError || !provider) {
    return (
      <ErrorState
        message="Couldn't load your hardware. Try again."
        onRetry={() => void refetch()}
      />
    );
  }

  const trustSource = trust?.trust_source ?? "self_report";
  const trustInfo = TRUST[trustSource] ?? {
    label: trustSource,
    tone: "neutral" as const,
    blurb: "Nothing has measured your hardware yet.",
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
          Hardware
        </h1>
        <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
          What you declare here is what the scheduler matches jobs against.
        </p>
      </div>

      {/* Capabilities */}
      <Card>
        <CardBody className="space-y-4">
          <div className="flex items-center justify-between">
            <CardTitle className="!mt-0">Declared capabilities</CardTitle>
            {!editing && (
              <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
                Edit
              </Button>
            )}
          </div>
          {editing ? (
            <CapabilitiesForm provider={provider} onDone={() => setEditing(false)} />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <ProviderStat label="GPU" value={provider.gpu_model ?? "None"} />
              <ProviderStat
                label="GPU VRAM"
                value={
                  provider.gpu_vram_mb ? `${(provider.gpu_vram_mb / 1024).toFixed(0)} GB` : "—"
                }
              />
              <ProviderStat label="CPU cores" value={provider.cpu_cores} />
              <ProviderStat label="Memory" value={`${(provider.memory_mb / 1024).toFixed(1)} GB`} />
              <ProviderStat label="Max concurrent" value={provider.max_concurrent} />
              <ProviderStat label="Region" value={provider.region ?? "—"} />
            </div>
          )}
        </CardBody>
      </Card>

      {/* Trust + health */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardBody className="space-y-3">
            <div className="flex items-center justify-between">
              <CardTitle className="!mt-0">Trust</CardTitle>
              <Badge tone={trustInfo.tone}>{trustInfo.label}</Badge>
            </div>
            <p className="text-sm text-[var(--color-ink-soft)]">{trustInfo.blurb}</p>
            <ul className="space-y-1 text-sm text-[var(--color-ink-faint)]">
              <li>Attested: {trust?.attested ? "yes" : "no"}</li>
              <li>Valid benchmark on file: {trust?.benchmarked ? "yes" : "no"}</li>
            </ul>
          </CardBody>
        </Card>

        <Card>
          <CardBody className="space-y-3">
            <div className="flex items-center justify-between">
              <CardTitle className="!mt-0">Health</CardTitle>
              <Badge tone={provider.degraded ? "warning" : provider.enabled ? "success" : "danger"}>
                {provider.degraded ? "Degraded" : provider.enabled ? "Healthy" : "Disabled"}
              </Badge>
            </div>
            <p className="text-sm text-[var(--color-ink-soft)]">
              {provider.degraded
                ? "The coordinator flagged your node degraded (GPU temp, throttling, or error rate). It won't receive new jobs until it recovers."
                : provider.enabled
                  ? "Your node is accepting work."
                  : "Your node is disabled and won't receive jobs."}
            </p>
            {bandwidth && (
              <dl className="grid grid-cols-2 gap-2 text-sm">
                <Meter label="Ingress" value={formatBytes(bandwidth.ingress_bytes)} />
                <Meter label="Egress" value={formatBytes(bandwidth.egress_bytes)} />
                <Meter label="Total served" value={formatBytes(bandwidth.total_bytes)} />
                <Meter label="This session" value={formatBytes(bandwidth.session_egress_bytes)} />
              </dl>
            )}
          </CardBody>
        </Card>
      </div>

      {/* Benchmark */}
      <Card>
        <CardBody className="space-y-3">
          <div className="flex items-center justify-between">
            <CardTitle className="!mt-0">Latest benchmark</CardTitle>
            {benchmark && (
              <Badge tone={benchmark.validated ? "success" : "warning"}>
                {benchmark.validated ? "Validated" : "Unvalidated"}
              </Badge>
            )}
          </div>
          {benchmark ? (
            <>
              <p className="text-sm text-[var(--color-ink-faint)]">
                Submitted <Timestamp iso={benchmark.created_at} />
                {!benchmark.validated &&
                  " — the measured hardware didn't match your declaration, so it wasn't accepted."}
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <tbody>
                    {Object.entries(benchmark.metrics ?? {}).map(([k, v]) => (
                      <tr key={k} className="border-t border-[var(--color-hairline)]">
                        <td className="py-2 pr-4 text-[var(--color-ink-faint)]">{k}</td>
                        <td className="py-2 font-[var(--font-mono)] text-[var(--color-ink)]">
                          {typeof v === "object" ? JSON.stringify(v) : String(v)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="text-sm text-[var(--color-ink-soft)]">
              No benchmark yet. The agent measures your GPU at onboarding and submits a signed
              report — once it does, it appears here and raises your trust tier.
            </p>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function Meter({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-[var(--color-ink-faint)]">{label}</dt>
      <dd className="font-[var(--font-mono)] text-[var(--color-ink)]">{value}</dd>
    </div>
  );
}
