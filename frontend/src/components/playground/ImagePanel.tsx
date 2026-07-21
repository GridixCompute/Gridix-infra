"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { generateImage, inferenceErrorMessage } from "@/lib/inference/client";
import { imagePriceBase } from "@/lib/inference/pricing";
import { toBaseUnits } from "@/lib/format/usdc";
import type { ImageGenerationRequest, ModelInfo } from "@/lib/inference/contract";
import type { ImageParams } from "@/lib/inference/params";
import { CodeViewDialog } from "./CodeViewDialog";

/**
 * Image generation.
 *
 * There is no partial output, so the wait is the whole experience: a real progress state,
 * cancellable, and the price known up front (per image, not per token — which is why the gate
 * here can be exact rather than a worst case).
 *
 * ⚠️ `size` and `steps` are gone. Neither exists on `ImageGenerationRequest`; the panel used
 * to collect both and send them, and the backend would have ignored them while the UI
 * captioned every result with a resolution it never requested.
 */

type Generation = {
  id: string;
  /** The URL the node returned. Nodes return references to stored artefacts, never bytes. */
  src: string;
  prompt: string;
  seed: number | null;
  costBase: bigint;
};

type Props = {
  model: ModelInfo | undefined;
  params: ImageParams;
  /** Available balance in base units (6dp), or null when it can't be read. */
  availableBase: bigint | null;
};

let seq = 0;

function buildRequest(
  model: ModelInfo,
  prompt: string,
  params: ImageParams,
): ImageGenerationRequest {
  return {
    model: model.id,
    prompt,
    seed: params.seed,
    n: 1,
    data_tier: "public",
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
  // Null means the rate card could not be parsed — the gate stays open rather than treating
  // an unreadable price as free, and the node refuses if it truly cannot be paid.
  const costBase = imagePriceBase(model);
  const unaffordable = availableBase !== null && costBase !== null && costBase > availableBase;
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
      const url = res.data[0]?.url;
      if (!url) throw new Error("empty response");
      setHistory((prev) => [
        {
          id: `gen-${++seq}`,
          src: url,
          prompt: text,
          seed: params.seed,
          // What was actually charged, straight off the response — never the estimate.
          costBase: toBaseUnits(res.cost_usdc),
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
  }, [prompt, model, params, busy, blocked]);

  const latest = history[0];
  const spentBase = history.reduce((sum, g) => sum + g.costBase, 0n);

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
            <p className="text-sm text-[var(--color-ink-faint)]">Generating…</p>
          </div>
        ) : latest ? (
          <figure className="space-y-3">
            {/* eslint-disable-next-line @next/next/no-img-element -- an arbitrary node-supplied
                URL; next/image needs a configured remote host, which this has not got. */}
            <img
              src={latest.src}
              alt={latest.prompt}
              className="mx-auto max-h-[26rem] w-auto rounded-[var(--radius-sm)]"
            />
            <figcaption className="flex flex-wrap items-center justify-center gap-3 text-xs text-[var(--color-ink-faint)]">
              <span>seed {latest.seed ?? "auto"}</span>
              <USDCAmount base={latest.costBase} minFractionDigits={6} />
              {/* No extension guessed from the payload: the node names the artefact, and
                  `download` without a value lets the response's own filename stand. */}
              <a href={latest.src} download className="text-[var(--color-signal-bright)] underline">
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
                {/* eslint-disable-next-line @next/next/no-img-element -- see above */}
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
      {unaffordable && costBase !== null && (
        <p role="alert" className="text-sm text-[var(--color-warning)]">
          Each image costs <USDCAmount base={costBase} minFractionDigits={6} /> — more than your
          balance.{" "}
          <a href="/billing" className="text-[var(--color-signal-bright)] underline">
            Top up
          </a>{" "}
          to continue.
        </p>
      )}
      {model && !model.available && (
        <p role="alert" className="text-sm text-[var(--color-warning)]">
          No provider is serving {model.id} right now. Pick another model.
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
            {costBase !== null && (
              <span>
                per image <USDCAmount base={costBase} minFractionDigits={6} />
              </span>
            )}
            {spentBase > 0n && (
              <span>
                spent <USDCAmount base={spentBase} minFractionDigits={6} />
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
