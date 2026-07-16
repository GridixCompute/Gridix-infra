"use client";

import { useMemo, useState } from "react";
import { useAccount } from "wagmi";
import { Card, CardBody, CardTitle } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { useModels } from "@/lib/hooks/useModels";
import { useBillingSummary } from "@/lib/hooks/useBilling";
import { useEscrowBalance } from "@/lib/chain/hooks";
import { toBaseUnits } from "@/lib/format/usdc";
import type { ChatParams } from "@/lib/inference/types";
import { ChatPanel } from "./ChatPanel";
import { SettingsPanel } from "./SettingsPanel";
import { MockBanner } from "./MockBanner";

/**
 * Playground shell (Sesi 4.1): mode + model selection around a panel.
 *
 * Balance is the app's real one — on-chain escrow minus what the ledger holds, the same
 * derivation the billing page reconciles against. The inference product's own deposit-address
 * balance (Sesi 6) does not exist yet, and inventing a number here would have made the
 * balance gate a prop.
 */

const DEFAULT_PARAMS: ChatParams = { temperature: 0.7, maxTokens: 512, topP: 1, seed: null };

type Mode = "chat" | "image";

export function PlaygroundShell() {
  const [mode, setMode] = useState<Mode>("chat");
  const [modelId, setModelId] = useState<string | null>(null);
  const [params, setParams] = useState<ChatParams>(DEFAULT_PARAMS);

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

  const forMode = useMemo(() => (models ?? []).filter((m) => m.kind === mode), [models, mode]);
  const selected = forMode.find((m) => m.id === modelId) ?? forMode[0];

  return (
    <div className="space-y-6">
      <MockBanner />

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
                  {m.name}
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
                <EmptyState
                  title="Image generation is next"
                  description="The image panel lands in Sesi 5, alongside /v1/images/generations."
                />
              )}
            </CardBody>
          </Card>

          <div className="space-y-4">
            {mode === "chat" && (
              <SettingsPanel params={params} onChange={setParams} disabled={!selected} />
            )}
            {selected && (
              <Card>
                <CardBody className="space-y-2">
                  <CardTitle className="!mt-0">Rate card</CardTitle>
                  <dl className="space-y-1.5 text-sm">
                    {selected.kind === "chat" ? (
                      <>
                        <div className="flex justify-between gap-3">
                          <dt className="text-[var(--color-ink-faint)]">Input / 1K</dt>
                          <dd className="font-[var(--font-mono)] text-[var(--color-ink-soft)]">
                            {selected.pricePer1kInput} µUSDC
                          </dd>
                        </div>
                        <div className="flex justify-between gap-3">
                          <dt className="text-[var(--color-ink-faint)]">Output / 1K</dt>
                          <dd className="font-[var(--font-mono)] text-[var(--color-ink-soft)]">
                            {selected.pricePer1kOutput} µUSDC
                          </dd>
                        </div>
                        {selected.contextWindow && (
                          <div className="flex justify-between gap-3">
                            <dt className="text-[var(--color-ink-faint)]">Context</dt>
                            <dd className="font-[var(--font-mono)] text-[var(--color-ink-soft)]">
                              {selected.contextWindow.toLocaleString()}
                            </dd>
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="flex justify-between gap-3">
                        <dt className="text-[var(--color-ink-faint)]">Per image</dt>
                        <dd className="font-[var(--font-mono)] text-[var(--color-ink-soft)]">
                          {selected.pricePerImage} µUSDC
                        </dd>
                      </div>
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
