"use client";

import type { ChatParams } from "@/lib/inference/types";
import { Card, CardBody, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";

/**
 * Generation knobs (Session 4.4). `seed` is the interesting one: pinning it makes a completion
 * reproducible, which is what the backend's canary determinism check relies on.
 */

type Props = {
  params: ChatParams;
  onChange: (next: ChatParams) => void;
  disabled?: boolean;
};

function Slider({
  label,
  hint,
  value,
  min,
  max,
  step,
  disabled,
  onChange,
}: {
  label: string;
  hint: string;
  value: number;
  min: number;
  max: number;
  step: number;
  disabled?: boolean;
  onChange: (v: number) => void;
}) {
  const id = `param-${label.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <label htmlFor={id} className="text-sm text-[var(--color-ink-soft)]">
          {label}
        </label>
        <span className="text-sm font-[var(--font-mono)] text-[var(--color-ink)]">{value}</span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1 w-full cursor-pointer appearance-none rounded-full bg-[var(--color-hairline-strong)] accent-[var(--color-signal)] focus-visible:ring-2 focus-visible:ring-[var(--color-signal)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-panel)] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50"
      />
      <p className="text-xs text-[var(--color-ink-faint)]">{hint}</p>
    </div>
  );
}

export function SettingsPanel({ params, onChange, disabled }: Props) {
  const set = <K extends keyof ChatParams>(key: K, value: ChatParams[K]) =>
    onChange({ ...params, [key]: value });

  return (
    <Card>
      <CardBody className="space-y-5">
        <CardTitle className="!mt-0">Parameters</CardTitle>

        <Slider
          label="Temperature"
          hint="Higher is more random. 0 is close to deterministic."
          value={params.temperature}
          min={0}
          max={2}
          step={0.1}
          disabled={disabled}
          onChange={(v) => set("temperature", v)}
        />
        <Slider
          label="Top P"
          hint="Nucleus sampling: consider tokens within this probability mass."
          value={params.topP}
          min={0.1}
          max={1}
          step={0.05}
          disabled={disabled}
          onChange={(v) => set("topP", v)}
        />
        <Slider
          label="Max tokens"
          hint="Caps the reply — and the price the estimate assumes."
          value={params.maxTokens}
          min={64}
          max={4096}
          step={64}
          disabled={disabled}
          onChange={(v) => set("maxTokens", v)}
        />

        <Input
          label="Seed"
          hint="Pin for a reproducible reply. Blank lets the node choose."
          placeholder="auto"
          mono
          inputMode="numeric"
          disabled={disabled}
          value={params.seed ?? ""}
          onChange={(e) => {
            const raw = e.target.value.trim();
            set("seed", raw === "" ? null : Number.parseInt(raw, 10) || null);
          }}
        />
      </CardBody>
    </Card>
  );
}
