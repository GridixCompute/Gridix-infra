"use client";

import { Card, CardBody, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import type { ImageParams } from "@/lib/inference/params";

/**
 * Image generation knobs.
 *
 * Only `seed`, because `seed` is the only knob `ImageGenerationRequest` carries besides the
 * prompt, the model and `n`. A Size radio group and a Steps slider used to sit here; the API
 * accepts neither, so both were controls that changed a request field that did not exist and
 * a caption on a result they had not influenced. They are not "not wired up yet" — there is
 * nothing on the backend to wire them to, and inventing UI for it is how the deleted
 * `types.ts` grew its fictions in the first place.
 */

type Props = {
  params: ImageParams;
  onChange: (next: ImageParams) => void;
  disabled?: boolean;
};

export function ImageSettingsPanel({ params, onChange, disabled }: Props) {
  return (
    <Card>
      <CardBody className="space-y-5">
        <CardTitle className="!mt-0">Parameters</CardTitle>

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
            onChange({ ...params, seed: raw === "" ? null : Number.parseInt(raw, 10) || null });
          }}
        />

        <p className="text-xs text-[var(--color-ink-faint)]">
          Size and step count aren&apos;t part of the image API — the node decides both, and the
          price is flat per image.
        </p>
      </CardBody>
    </Card>
  );
}
