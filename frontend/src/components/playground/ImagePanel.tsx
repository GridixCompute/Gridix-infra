"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { generateImage, inferenceErrorMessage } from "@/lib/inference/client";
import { microToBase } from "@/lib/inference/pricing";
import type { ImageParams, ImageRequest, InferenceModel } from "@/lib/inference/types";
import { CodeViewDialog } from "./CodeViewDialog";

/**
 * Image generation (Sesi 5.2).
 *
 * Unlike chat there is no partial output, so the wait is the whole experience: a real
 * progress state, cancellable, and the price known up front (per image, not per token —
 * which is why the gate here can be exact rather than a worst case).
 */

type Generation = {
  id: string;
  /** `data:` URL built from the response's base64 payload. */
  src: string;
  prompt: string;
  size: string;
  seed: number | null;
  costMicro: number;
};

type Props = {
  model: InferenceModel | undefined;
  params: ImageParams;
  /** Available balance in base units (6dp), or null when it can't be read. */
  availableBase: bigint | null;
};

let seq = 0;

function buildRequest(model: InferenceModel, prompt: string, params: ImageParams): ImageRequest {
  return {
    model: model.id,
    prompt,
    size: params.size,
    steps: params.steps,
    seed: params.seed,
    n: 1,
  };
}

export function ImagePanel({ model, params, availableBase }: Props) {
  const [prompt, setPrompt] = useState("");
  const [history, setHistory] = useState<Generation[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCode, setShowCode] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  // Per-image pricing: the cost is known exactly before sending, so no worst-case padding.
  const costMicro = model?.pricePerImage ?? 0;
  const unaffordable =
    availableBase !== null && model !== undefined && microToBase(costMicro) > availableBase;
  const blocked = !model?.available || unaffordable;

  const generate = useCallback(async () => {
    const text = prompt.trim();
    if (!text || !model || busy || blocked) return;

    setBusy(true);
    setError(null);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await generateImage(buildRequest(model, text, params), controller.signal);
      const b64 = res.data[0]?.b64_json;
      if (!b64) throw new Error("empty response");
      setHistory((prev) => [
        {
          id: `gen-${++seq}`,
          // The mock returns SVG; a real model returns PNG. Both ride the same field, so
          // sniff rather than assume — an <img> with the wrong type renders nothing.
          src: `data:${b64.startsWith("PHN2Zy") ? "image/svg+xml" : "image/png"};base64,${b64}`,
          prompt: text,
          size: params.size,
          seed: params.seed,
          costMicro: res.usage?.cost_micro_usdc ?? costMicro,
        },
        ...prev,
      ]);
    } catch (e) {
      // A cancel is not a failure — say nothing and leave the panel as it was.
      if ((e as Error)?.name !== "AbortError") setError(inferenceErrorMessage(e));
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }, [prompt, model, params, busy, blocked, costMicro]);

  const latest = history[0];
  const spentMicro = history.reduce((sum, g) => sum + g.costMicro, 0);

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex min-h-[22rem] flex-1 items-center justify-center rounded-[var(--radius-md)] border border-[var(--color-hairline)] bg-[var(--color-panel)] p-4">
        {busy ? (
          <div className="space-y-3 text-center">
            <div
              role="status"
              aria-label="Generating"
              className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-[var(--color-hairline-strong)] border-t-[var(--color-signal)]"
            />
            <p className="text-sm text-[var(--color-ink-faint)]">
              Generating at {params.size}, {params.steps} steps…
            </p>
          </div>
        ) : latest ? (
          <figure className="space-y-3">
            {/* eslint-disable-next-line @next/next/no-img-element -- a data: URL from the
                response; next/image is for URLs it can optimise, which this is not. */}
            <img
              src={latest.src}
              alt={latest.prompt}
              className="mx-auto max-h-[26rem] w-auto rounded-[var(--radius-sm)]"
            />
            <figcaption className="flex flex-wrap items-center justify-center gap-3 text-xs text-[var(--color-ink-faint)]">
              <span>{latest.size}</span>
              <span>seed {latest.seed ?? "auto"}</span>
              <USDCAmount base={microToBase(latest.costMicro)} minFractionDigits={6} />
              <a
                href={latest.src}
                download={`gridix-${latest.id}.${latest.src.includes("svg") ? "svg" : "png"}`}
                className="text-[var(--color-signal-bright)] underline"
              >
                Download
              </a>
            </figcaption>
          </figure>
        ) : (
          <p className="text-sm text-[var(--color-ink-faint)]">
            Describe an image to generate one.
          </p>
        )}
      </div>

      {history.length > 1 && (
        <div>
          <p className="mb-2 text-xs text-[var(--color-ink-faint)]">History</p>
          <ul className="flex gap-2 overflow-x-auto pb-1">
            {history.slice(1).map((g) => (
              <li key={g.id} className="shrink-0">
                {/* eslint-disable-next-line @next/next/no-img-element -- data: URL, see above */}
                <img
                  src={g.src}
                  alt={g.prompt}
                  title={g.prompt}
                  className="h-16 w-16 rounded-[var(--radius-xs)] border border-[var(--color-hairline)] object-cover"
                />
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && (
        <p role="alert" className="text-sm text-[var(--color-danger)]">
          {error}
        </p>
      )}
      {unaffordable && (
        <p role="alert" className="text-sm text-[var(--color-warning)]">
          Each image costs <USDCAmount base={microToBase(costMicro)} minFractionDigits={6} /> — more
          than your balance.{" "}
          <a href="/billing" className="text-[var(--color-signal-bright)] underline">
            Top up
          </a>{" "}
          to continue.
        </p>
      )}
      {model && !model.available && (
        <p role="alert" className="text-sm text-[var(--color-warning)]">
          No provider is serving {model.name} right now. Pick another model.
        </p>
      )}

      <div className="space-y-2">
        <textarea
          aria-label="Image prompt"
          rows={3}
          value={prompt}
          disabled={blocked}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void generate();
          }}
          placeholder={blocked ? "Generating is blocked — see above." : "A wireframe globe…  (⌘↵)"}
          className="w-full resize-y rounded-[var(--radius-md)] border border-[var(--color-hairline)] bg-[var(--color-panel)] px-3.5 py-2.5 text-sm text-[var(--color-ink)] placeholder:text-[var(--color-ink-disabled)] focus-visible:border-[var(--color-signal)] focus-visible:ring-2 focus-visible:ring-[var(--color-signal-glow)] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60"
        />

        <div className="flex flex-wrap items-center gap-3">
          {busy ? (
            <Button variant="secondary" onClick={() => abortRef.current?.abort()}>
              Cancel
            </Button>
          ) : (
            <Button onClick={() => void generate()} disabled={!prompt.trim() || blocked}>
              Generate
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowCode(true)}
            disabled={!model || !prompt.trim()}
          >
            View code
          </Button>

          <span className="ml-auto flex items-center gap-3 text-xs text-[var(--color-ink-faint)]">
            <span>
              per image <USDCAmount base={microToBase(costMicro)} minFractionDigits={6} />
            </span>
            {spentMicro > 0 && (
              <span>
                spent <USDCAmount base={microToBase(spentMicro)} minFractionDigits={6} />
              </span>
            )}
            {availableBase !== null && (
              <span>
                balance <USDCAmount base={availableBase} tone="signal" />
              </span>
            )}
          </span>
        </div>
      </div>

      {model && (
        <CodeViewDialog
          open={showCode}
          onClose={() => setShowCode(false)}
          path="/v1/images/generations"
          body={buildRequest(model, prompt.trim(), params)}
        />
      )}
    </div>
  );
}
