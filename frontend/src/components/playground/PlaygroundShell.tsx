"use client";

import { useMemo, useState } from "react";
import { useAccount } from "wagmi";
import { Card, CardBody, CardTitle } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/States";
import { useModels } from "@/lib/hooks/useModels";
import { useBillingSummary } from "@/lib/hooks/useBilling";
import { useEscrowBalance } from "@/lib/chain/hooks";
import { toBaseUnits } from "@/lib/format/usdc";
import { priceToBase } from "@/lib/inference/pricing";
import { USDCAmount } from "@/components/domain/USDCAmount";
import type { ChatParams, ImageParams } from "@/lib/inference/params";
import { ChatPanel } from "./ChatPanel";
import { ImagePanel } from "./ImagePanel";
import { SettingsPanel } from "./SettingsPanel";
import { ImageSettingsPanel } from "./ImageSettingsPanel";
import { MockBanner } from "./MockBanner";

/**
 * Playground shell (Session 4.1): mode + model selection around a panel.
 *
 * Balance is the app's real one — on-chain escrow minus what the ledger holds, the same
 * derivation the billing page reconciles against. The inference product's own deposit-address
 * balance (Session 6) does not exist yet, and inventing a number here would have made the
 * balance gate a prop.
 */

const DEFAULT_PARAMS: ChatParams = { temperature: 0.7, maxTokens: 512, seed: null };
const DEFAULT_IMAGE_PARAMS: ImageParams = { seed: null };

type Mode = "chat" | "image";

/** One rate-card line. An unparseable price shows as unknown rather than as zero. */
function RateRow({ label, usdc }: { label: string; usdc: string }) {
  const base = priceToBase(usdc);
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-[var(--color-ink-faint)]">{label}</dt>
      <dd className="font-[var(--font-mono)] text-[var(--color-ink-soft)]">
        {base === null ? "—" : <USDCAmount base={base} minFractionDigits={2} />}
      </dd>
    </div>
  );
}

export function PlaygroundShell() {
  const [mode, setMode] = useState<Mode>("chat");
  const [modelId, setModelId] = useState<string | null>(null);
  const [params, setParams] = useState<ChatParams>(DEFAULT_PARAMS);
  const [imageParams, setImageParams] = useState<ImageParams>(DEFAULT_IMAGE_PARAMS);

  const { data: models, isLoading, error, refetch } = useModels();
  const { address } = useAccount();
  const { data: escrow } = useEscrowBalance(address);
  const { data: summary } = useBillingSummary();

  const availableBase = useMemo(() => {
    if (escrow === undefined || !summary) return null;
    const held = toBaseUnits(summary.total_held);
    const balance = escrow as bigint;
    return balance > held ? balance - held : 0n;
  }, [escrow, summary]);

  /**
   * Why the balance is missing, when it is.
   *
   * A null balance disables the spend guard, and three unrelated causes produce one — no
   * wallet, no ledger, still loading. Collapsing them into a silently absent line lets the
   * page look normal while the thing that stops an unaffordable request is switched off.
   * So say which, and say that the guard is off.
   */
  const balanceGap = !address
    ? "Connect a wallet to see your balance — until then, the spend guard is off."
    : escrow === undefined
      ? "Reading your on-chain balance… the spend guard is off until it loads."
      : !summary
        ? "Your balance can't be read right now, so the spend guard is off. Requests may be refused by the node."
        : null;

  const forMode = useMemo(() => (models ?? []).filter((m) => m.modality === mode), [models, mode]);
  const selected = forMode.find((m) => m.id === modelId) ?? forMode[0];

  return (
    <div className="space-y-6">
      <MockBanner />

      {balanceGap && (
        <p
          role="status"
          className="rounded-[var(--radius-sm)] border border-[var(--color-hairline)] bg-[var(--color-panel)] px-3 py-2 text-sm text-[var(--color-ink-faint)]"
        >
          {balanceGap}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-4">
        <div role="tablist" aria-label="Inference mode" className="flex gap-1">
          {(["chat", "image"] as const).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              onClick={() => {
                setMode(m);
                setModelId(null);
              }}
              className={[
                "rounded-[var(--radius-sm)] px-3.5 py-1.5 text-sm capitalize transition-colors",
                "focus-visible:ring-2 focus-visible:ring-[var(--color-signal)] focus-visible:outline-none",
                mode === m
                  ? "bg-[var(--color-signal)] font-medium text-[var(--color-void)]"
                  : "text-[var(--color-ink-soft)] hover:bg-[var(--color-panel)]",
              ].join(" ")}
            >
              {m}
            </button>
          ))}
        </div>

        {forMode.length > 0 && (
          <label className="flex items-center gap-2 text-sm">
            <span className="text-[var(--color-ink-faint)]">Model</span>
            <select
              value={selected?.id ?? ""}
              onChange={(e) => setModelId(e.target.value)}
              className="rounded-[var(--radius-sm)] border border-[var(--color-hairline)] bg-[var(--color-panel)] px-3 py-1.5 text-sm text-[var(--color-ink)] focus-visible:border-[var(--color-signal)] focus-visible:ring-2 focus-visible:ring-[var(--color-signal-glow)] focus-visible:outline-none"
            >
              {forMode.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.id}
                  {m.available ? "" : " — unavailable"}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {isLoading && <Skeleton className="h-[28rem] w-full" />}
      {error && (
        <ErrorState message="Couldn't load the model list." onRetry={() => void refetch()} />
      )}

      {!isLoading && !error && (
        <div className="grid gap-6 lg:grid-cols-[1fr_18rem]">
          <Card>
            <CardBody className="h-full">
              {mode === "chat" ? (
                <ChatPanel model={selected} params={params} availableBase={availableBase} />
              ) : (
                <ImagePanel model={selected} params={imageParams} availableBase={availableBase} />
              )}
            </CardBody>
          </Card>

          <div className="space-y-4">
            {mode === "chat" ? (
              <SettingsPanel params={params} onChange={setParams} disabled={!selected} />
            ) : (
              <ImageSettingsPanel
                params={imageParams}
                onChange={setImageParams}
                disabled={!selected}
              />
            )}
            {selected && (
              <Card>
                <CardBody className="space-y-2">
                  <CardTitle className="!mt-0">Rate card</CardTitle>
                  <dl className="space-y-1.5 text-sm">
                    {/* Rendered through USDCAmount, not interpolated raw: these are decimal
                        USDC strings from the API, and the previous card printed them with a
                        "µUSDC" suffix they never had. */}
                    {selected.modality === "chat" ? (
                      <>
                        <RateRow label="Input / 1M tok" usdc={selected.input_usdc_per_mtok} />
                        <RateRow label="Output / 1M tok" usdc={selected.output_usdc_per_mtok} />
                        <div className="flex justify-between gap-3">
                          <dt className="text-[var(--color-ink-faint)]">Context</dt>
                          <dd className="font-[var(--font-mono)] text-[var(--color-ink-soft)]">
                            {selected.context_window.toLocaleString()}
                          </dd>
                        </div>
                      </>
                    ) : (
                      <RateRow label="Per image" usdc={selected.usdc_per_image} />
                    )}
                  </dl>
                </CardBody>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
