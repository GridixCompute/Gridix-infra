"use client";

import { Card, CardBody, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { IMAGE_SIZES, type ImageParams, type ImageSize } from "@/lib/inference/types";

/** Image generation knobs (Sesi 5.2). `seed` pins determinism, same as chat. */

type Props = {
  params: ImageParams;
  onChange: (next: ImageParams) => void;
  disabled?: boolean;
};

export function ImageSettingsPanel({ params, onChange, disabled }: Props) {
  const set = <K extends keyof ImageParams>(key: K, value: ImageParams[K]) =>
    onChange({ ...params, [key]: value });

  return (
    <Card>
      <CardBody className="space-y-5">
        <CardTitle className="!mt-0">Parameters</CardTitle>

        <div className="space-y-1.5">
          <span className="text-sm text-[var(--color-ink-soft)]">Size</span>
          <div role="radiogroup" aria-label="Size" className="flex gap-1">
            {IMAGE_SIZES.map((s: ImageSize) => (
              <button
                key={s}
                role="radio"
                aria-checked={params.size === s}
                disabled={disabled}
                onClick={() => set("size", s)}
                className={[
                  "flex-1 rounded-[var(--radius-sm)] px-2 py-1.5 text-xs font-[var(--font-mono)] transition-colors",
                  "focus-visible:ring-2 focus-visible:ring-[var(--color-signal)] focus-visible:outline-none",
                  "disabled:cursor-not-allowed disabled:opacity-50",
                  params.size === s
                    ? "bg-[var(--color-signal)] font-medium text-[var(--color-void)]"
                    : "bg-[var(--color-panel-raised)] text-[var(--color-ink-soft)] hover:text-[var(--color-ink)]",
                ].join(" ")}
              >
                {s}
              </button>
            ))}
          </div>
          <p className="text-xs text-[var(--color-ink-faint)]">
            Bigger costs the provider more time — the price per image is flat here.
          </p>
        </div>

        <div className="space-y-1.5">
          <div className="flex items-baseline justify-between">
            <label htmlFor="param-steps" className="text-sm text-[var(--color-ink-soft)]">
              Steps
            </label>
            <span className="text-sm font-[var(--font-mono)] text-[var(--color-ink)]">
              {params.steps}
            </span>
          </div>
          <input
            id="param-steps"
            type="range"
            min={1}
            max={50}
            step={1}
            value={params.steps}
            disabled={disabled}
            onChange={(e) => set("steps", Number(e.target.value))}
            className="h-1 w-full cursor-pointer appearance-none rounded-full bg-[var(--color-hairline-strong)] accent-[var(--color-signal)] focus-visible:ring-2 focus-visible:ring-[var(--color-signal)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-panel)] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          />
          <p className="text-xs text-[var(--color-ink-faint)]">
            More steps, more detail, longer wait.
          </p>
        </div>

        <Input
          label="Seed"
          hint="Pin for a reproducible image. Blank lets the node choose."
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
