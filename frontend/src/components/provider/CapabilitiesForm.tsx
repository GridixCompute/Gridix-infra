"use client";

import { useState } from "react";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { useUpdateCapabilities } from "@/lib/hooks/useProvider";
import { isApiError } from "@/lib/api/errors";
import type { Provider } from "@/lib/api/types";

/**
 * Declare/edit the hardware the scheduler matches against (Sesi 11.3). Memory
 * and VRAM are entered in GB for humans and converted to the MB the API expects.
 */
export function CapabilitiesForm({ provider, onDone }: { provider: Provider; onDone: () => void }) {
  const update = useUpdateCapabilities();
  const [gpuModel, setGpuModel] = useState(provider.gpu_model ?? "");
  const [gpuVramGb, setGpuVramGb] = useState(
    provider.gpu_vram_mb ? String(provider.gpu_vram_mb / 1024) : "",
  );
  const [cpuCores, setCpuCores] = useState(String(provider.cpu_cores));
  const [memoryGb, setMemoryGb] = useState(String(provider.memory_mb / 1024));
  const [maxConcurrent, setMaxConcurrent] = useState(String(provider.max_concurrent));
  const [region, setRegion] = useState(provider.region ?? "");
  const [error, setError] = useState<string | null>(null);

  const toMb = (gb: string) => Math.round(Number(gb) * 1024);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await update.mutateAsync({
        gpu_model: gpuModel.trim() || null,
        gpu_vram_mb: gpuVramGb.trim() ? toMb(gpuVramGb) : 0,
        cpu_cores: Number(cpuCores),
        memory_mb: toMb(memoryGb),
        max_concurrent: Number(maxConcurrent),
        region: region.trim() || null,
      });
      onDone();
    } catch (err) {
      setError(
        isApiError(err) ? err.message : "Couldn't save your capabilities. Check the values.",
      );
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Input
          label="GPU model"
          placeholder="e.g. A100 (leave blank if none)"
          value={gpuModel}
          onChange={(e) => setGpuModel(e.target.value)}
        />
        <Input
          label="GPU VRAM (GB)"
          type="number"
          min={0}
          value={gpuVramGb}
          onChange={(e) => setGpuVramGb(e.target.value)}
        />
        <Input
          label="CPU cores"
          type="number"
          min={0}
          value={cpuCores}
          onChange={(e) => setCpuCores(e.target.value)}
          required
        />
        <Input
          label="Memory (GB)"
          type="number"
          min={0}
          step="0.5"
          value={memoryGb}
          onChange={(e) => setMemoryGb(e.target.value)}
          required
        />
        <Input
          label="Max concurrent jobs"
          type="number"
          min={1}
          value={maxConcurrent}
          onChange={(e) => setMaxConcurrent(e.target.value)}
          required
        />
        <Input
          label="Region"
          placeholder="e.g. eu-central"
          value={region}
          onChange={(e) => setRegion(e.target.value)}
        />
      </div>
      {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}
      <div className="flex gap-2">
        <Button type="submit" loading={update.isPending}>
          Save capabilities
        </Button>
        <Button type="button" variant="ghost" onClick={onDone} disabled={update.isPending}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
