"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { useSubmitJob } from "@/lib/hooks/useSubmitJob";
import { estimateCost } from "@/lib/pricing";
import { isApiError } from "@/lib/api/errors";
import { track } from "@/lib/observability/report";
import type { SubmitJobRequest } from "@/lib/api/types";

type EnvRow = { key: string; value: string };

export default function NewJobPage() {
  const router = useRouter();
  const submit = useSubmitJob();

  const [imageRef, setImageRef] = useState("");
  const [cpuCores, setCpuCores] = useState(1);
  const [memoryMb, setMemoryMb] = useState(512);
  const [gpu, setGpu] = useState(false);
  const [gpuVramMb, setGpuVramMb] = useState(16000);
  const [timeoutSeconds, setTimeoutSeconds] = useState(300);
  const [redundancy, setRedundancy] = useState(1);
  const [allowEgress, setAllowEgress] = useState(false);
  const [command, setCommand] = useState("");
  const [envRows, setEnvRows] = useState<EnvRow[]>([{ key: "", value: "" }]);

  // First-run sample (Sesi 14.2): /jobs/new?sample=1 prefills a tiny public
  // container a new developer can submit as-is to see the full flow.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("sample") === "1") {
      setImageRef("docker.io/library/hello-world");
      setCpuCores(1);
      setMemoryMb(512);
      setTimeoutSeconds(120);
    }
  }, []);

  const estimate = useMemo(
    () => estimateCost({ cpuCores, gpu, timeoutSeconds }),
    [cpuCores, gpu, timeoutSeconds],
  );

  // Client validation mirroring the backend (Sesi 7.5); the server 422 is final.
  const clientErrors = useMemo(() => {
    const e: Record<string, string> = {};
    if (!imageRef.trim()) e.image_ref = "Enter a container image reference.";
    if (gpu && gpuVramMb <= 0) e["resource_spec.gpu_vram_mb"] = "GPU jobs need VRAM > 0.";
    if (timeoutSeconds < 1 || timeoutSeconds > 86_400)
      e.timeout_seconds = "Timeout must be between 1 and 86400 seconds.";
    if (redundancy < 1 || redundancy > 10) e.redundancy = "Redundancy must be between 1 and 10.";
    return e;
  }, [imageRef, gpu, gpuVramMb, timeoutSeconds, redundancy]);

  const serverError = submit.error;
  function fieldError(name: string): string | undefined {
    if (clientErrors[name]) return clientErrors[name];
    if (isApiError(serverError)) return serverError.fieldError(name);
    return undefined;
  }

  const canSubmit = Object.keys(clientErrors).length === 0 && !submit.isPending;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;

    const env: Record<string, string> = {};
    for (const row of envRows) if (row.key.trim()) env[row.key.trim()] = row.value;
    const commandParts = command.trim() ? command.trim().split(/\s+/) : undefined;

    const body: SubmitJobRequest = {
      image_ref: imageRef.trim(),
      resource_spec: {
        cpu_cores: cpuCores,
        memory_mb: memoryMb,
        gpu,
        gpu_vram_mb: gpu ? gpuVramMb : 0,
      },
      args:
        commandParts || Object.keys(env).length
          ? { command: commandParts ?? null, env: Object.keys(env).length ? env : null }
          : null,
      allow_egress: allowEgress,
      timeout_seconds: timeoutSeconds,
      is_high_value: redundancy > 1,
      redundancy,
      data_tier: "public",
    };

    try {
      const job = await submit.mutateAsync(body);
      track("job_submitted", { gpu, redundancy });
      router.push(`/jobs/${job.id}`);
    } catch {
      /* error surfaced via submit.error / fieldError */
    }
  }

  const topLevelError =
    isApiError(serverError) && serverError.fieldErrors.length === 0 ? serverError.message : null;

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-6">
        <Link
          href="/dashboard"
          className="text-sm text-[var(--color-ink-faint)] hover:text-[var(--color-ink)]"
        >
          ← Jobs
        </Link>
        <h1 className="mt-2 text-2xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
          Submit a job
        </h1>
        <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
          Run a container on the GRIDIX network. Worst-case cost is escrowed now and reconciled to
          the actual compute used.
        </p>
      </div>

      <form onSubmit={onSubmit} className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Container</CardTitle>
            </CardHeader>
            <CardBody className="space-y-4">
              <Input
                label="Image reference"
                placeholder="ghcr.io/acme/train:latest"
                value={imageRef}
                onChange={(e) => setImageRef(e.target.value)}
                error={fieldError("image_ref")}
                mono
                autoFocus
              />
              <Input
                label="Command (optional)"
                placeholder="python train.py --epochs 10"
                value={command}
                onChange={(e) => setCommand(e.target.value)}
                mono
                hint="Overrides the image entrypoint. Space-separated."
              />
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Resources</CardTitle>
            </CardHeader>
            <CardBody className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <NumberField
                  label="CPU cores"
                  value={cpuCores}
                  min={1}
                  max={64}
                  onChange={setCpuCores}
                />
                <NumberField
                  label="Memory (MB)"
                  value={memoryMb}
                  min={128}
                  max={262144}
                  step={128}
                  onChange={setMemoryMb}
                />
              </div>
              <Toggle
                checked={gpu}
                onChange={setGpu}
                label="Requires a GPU"
                description="Priced at 4× CPU-seconds."
              />
              {gpu && (
                <NumberField
                  label="GPU VRAM (MB)"
                  value={gpuVramMb}
                  min={1}
                  max={200000}
                  step={1000}
                  onChange={setGpuVramMb}
                  error={fieldError("resource_spec.gpu_vram_mb")}
                />
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Execution</CardTitle>
            </CardHeader>
            <CardBody className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <NumberField
                  label="Timeout (seconds)"
                  value={timeoutSeconds}
                  min={1}
                  max={86400}
                  onChange={setTimeoutSeconds}
                  error={fieldError("timeout_seconds")}
                />
                <NumberField
                  label="Redundancy (K)"
                  value={redundancy}
                  min={1}
                  max={10}
                  onChange={setRedundancy}
                  error={fieldError("redundancy")}
                  hint={redundancy > 1 ? "Runs on K providers; settles by quorum." : undefined}
                />
              </div>
              <Toggle
                checked={allowEgress}
                onChange={setAllowEgress}
                label="Allow network egress"
                description="Off by default — the container runs with no network access."
              />
              <EnvEditor rows={envRows} onChange={setEnvRows} />
            </CardBody>
          </Card>
        </div>

        {/* Cost + submit rail */}
        <div className="space-y-4 lg:sticky lg:top-24 lg:self-start">
          <Card>
            <CardHeader>
              <CardTitle>Estimated cost</CardTitle>
            </CardHeader>
            <CardBody className="space-y-3 text-sm">
              <Row label="Compute (escrowed)" value={<USDCAmount base={estimate.computeBase} />} />
              <Row
                label="Protocol fee (2.5%)"
                value={<USDCAmount base={estimate.feeBase} tone="muted" />}
              />
              <div className="border-t border-[var(--color-hairline)] pt-3">
                <Row
                  label={<span className="text-[var(--color-ink)]">Worst-case total</span>}
                  value={<USDCAmount base={estimate.totalBase} tone="signal" />}
                />
              </div>
              <p className="pt-1 text-xs text-[var(--color-ink-faint)]">
                You&apos;re charged for actual compute used; unused escrow is refunded when the job
                settles.
              </p>
            </CardBody>
          </Card>

          {topLevelError && (
            <div className="rounded-[var(--radius-sm)] border border-[#ff5c5c55] bg-[#ff5c5c1a] p-3 text-sm text-[var(--color-danger)]">
              {topLevelError}
              {isApiError(serverError) && serverError.kind === "forbidden" && (
                <Link href="/billing" className="mt-1 block underline">
                  Deposit USDC
                </Link>
              )}
            </div>
          )}

          <Button
            type="submit"
            size="lg"
            className="w-full"
            loading={submit.isPending}
            disabled={!canSubmit}
          >
            Submit job
          </Button>
        </div>
      </form>
    </div>
  );
}

function Row({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[var(--color-ink-faint)]">{label}</span>
      {value}
    </div>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step,
  onChange,
  error,
  hint,
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onChange: (v: number) => void;
  error?: string;
  hint?: string;
}) {
  return (
    <Input
      label={label}
      type="number"
      inputMode="numeric"
      value={Number.isFinite(value) ? value : ""}
      min={min}
      max={max}
      step={step}
      onChange={(e) => onChange(Number(e.target.value))}
      error={error}
      hint={hint}
      mono
    />
  );
}

function Toggle({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  description?: string;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--color-signal)]"
      />
      <span>
        <span className="block text-sm text-[var(--color-ink)]">{label}</span>
        {description && (
          <span className="block text-xs text-[var(--color-ink-faint)]">{description}</span>
        )}
      </span>
    </label>
  );
}

function EnvEditor({ rows, onChange }: { rows: EnvRow[]; onChange: (r: EnvRow[]) => void }) {
  function update(i: number, patch: Partial<EnvRow>) {
    onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  }
  return (
    <div className="space-y-2">
      <span className="block text-sm font-medium text-[var(--color-ink-soft)]">
        Environment variables
      </span>
      {rows.map((row, i) => (
        <div key={i} className="flex gap-2">
          <Input
            placeholder="KEY"
            value={row.key}
            onChange={(e) => update(i, { key: e.target.value })}
            mono
            className="uppercase"
          />
          <Input
            placeholder="value"
            value={row.value}
            onChange={(e) => update(i, { value: e.target.value })}
            mono
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="Remove variable"
            onClick={() => onChange(rows.filter((_, idx) => idx !== i))}
          >
            ✕
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={() => onChange([...rows, { key: "", value: "" }])}
      >
        Add variable
      </Button>
    </div>
  );
}
