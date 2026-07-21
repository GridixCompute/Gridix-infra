"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { useModels } from "@/lib/hooks/useModels";
import { priceToBase } from "@/lib/inference/pricing";
import type { ModelInfo } from "@/lib/inference/contract";
import { MockBanner } from "./MockBanner";

/**
 * The catalogue and its rate card.
 *
 * Chat is priced per token and image per image, so the two cannot share a price column
 * honestly — one row would have to lie about its unit. They get separate tables instead.
 * Availability is per-model and can flip as providers come and go, so it is shown, not
 * assumed; an unavailable model still lists its price, because the price is what you'd pay
 * when it returns.
 *
 * ⚠️ The unit is per 1,000,000 tokens, which is how the backend prices and reports it. This
 * table used to say "/ 1K tok" over a number it read as micro-USDC — a label and a unit that
 * were both wrong, and would have under-reported the rate card by 1000× against the real API.
 */

function Price({ usdc, unit }: { usdc: string; unit: string }) {
  const base = priceToBase(usdc);
  if (base === null) return <span className="text-[var(--color-ink-disabled)]">—</span>;
  return (
    <span className="whitespace-nowrap">
      <USDCAmount base={base} minFractionDigits={2} />
      <span className="text-[var(--color-ink-faint)]"> / {unit}</span>
    </span>
  );
}

function Availability({ available }: { available: boolean }) {
  return available ? (
    <Badge tone="success">available</Badge>
  ) : (
    <Badge tone="neutral">no provider</Badge>
  );
}

function ChatTable({ models }: { models: ModelInfo[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-[var(--color-ink-faint)]">
          <tr className="border-b border-[var(--color-hairline)]">
            <th className="py-2 pr-4 font-medium">Model</th>
            <th className="py-2 pr-4 font-medium">Input</th>
            <th className="py-2 pr-4 font-medium">Output</th>
            <th className="py-2 pr-4 font-medium">Context</th>
            <th className="py-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.id} className="border-b border-[var(--color-hairline)] last:border-0">
              {/* The id is the name: ModelInfo carries no display label, and inventing one
                  client-side would be a second source of truth for what a model is called. */}
              <td className="py-3 pr-4">
                <code className="text-xs font-[var(--font-mono)] text-[var(--color-ink)]">
                  {m.id}
                </code>
              </td>
              <td className="py-3 pr-4">
                <Price usdc={m.input_usdc_per_mtok} unit="1M tok" />
              </td>
              <td className="py-3 pr-4">
                <Price usdc={m.output_usdc_per_mtok} unit="1M tok" />
              </td>
              <td className="py-3 pr-4 text-xs font-[var(--font-mono)] text-[var(--color-ink-soft)]">
                {m.context_window.toLocaleString()}
              </td>
              <td className="py-3">
                <Availability available={m.available} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ImageTable({ models }: { models: ModelInfo[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-[var(--color-ink-faint)]">
          <tr className="border-b border-[var(--color-hairline)]">
            <th className="py-2 pr-4 font-medium">Model</th>
            <th className="py-2 pr-4 font-medium">Price</th>
            <th className="py-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.id} className="border-b border-[var(--color-hairline)] last:border-0">
              <td className="py-3 pr-4">
                <code className="text-xs font-[var(--font-mono)] text-[var(--color-ink)]">
                  {m.id}
                </code>
              </td>
              <td className="py-3 pr-4">
                <Price usdc={m.usdc_per_image} unit="image" />
              </td>
              <td className="py-3">
                <Availability available={m.available} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ModelsTable() {
  const { data, isLoading, error, refetch } = useModels();

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error) {
    return <ErrorState message="Couldn't load the model list." onRetry={() => void refetch()} />;
  }

  const chat = (data ?? []).filter((m) => m.modality === "chat");
  const image = (data ?? []).filter((m) => m.modality === "image");

  if (chat.length + image.length === 0) {
    return (
      <EmptyState
        title="No models"
        description="No provider is serving a model right now. Check back shortly."
      />
    );
  }

  return (
    <div className="space-y-8">
      <MockBanner />

      {chat.length > 0 && (
        <section className="space-y-3">
          <div>
            <h2 className="text-lg font-[var(--font-display)] font-bold text-[var(--color-ink)]">
              Chat
            </h2>
            <p className="text-sm text-[var(--color-ink-faint)]">
              Priced per million tokens, split between what you send and what the model writes back.
            </p>
          </div>
          <ChatTable models={chat} />
        </section>
      )}

      {image.length > 0 && (
        <section className="space-y-3">
          <div>
            <h2 className="text-lg font-[var(--font-display)] font-bold text-[var(--color-ink)]">
              Image
            </h2>
            <p className="text-sm text-[var(--color-ink-faint)]">
              Priced per generated image. The node chooses the size.
            </p>
          </div>
          <ImageTable models={image} />
        </section>
      )}

      <p className="text-sm text-[var(--color-ink-faint)]">
        Try any of these in the{" "}
        <Link href="/playground" className="text-[var(--color-signal-bright)] underline">
          playground
        </Link>
        .
      </p>
    </div>
  );
}
