"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { useModels } from "@/lib/hooks/useModels";
import { microToBase } from "@/lib/inference/pricing";
import type { InferenceModel } from "@/lib/inference/types";
import { MockBanner } from "./MockBanner";

/**
 * The catalogue and its rate card (Session 5.4).
 *
 * Chat is priced per token and image per image, so the two cannot share a price column
 * honestly — one row would have to lie about its unit. They get separate tables instead.
 * Availability is per-model and can flip as providers come and go, so it is shown, not
 * assumed; an unavailable model still lists its price, because the price is what you'd pay
 * when it returns.
 */

function Price({ micro, unit }: { micro: number | undefined; unit: string }) {
  if (micro === undefined) return <span className="text-[var(--color-ink-disabled)]">—</span>;
  return (
    <span className="whitespace-nowrap">
      <USDCAmount base={microToBase(micro)} minFractionDigits={6} />
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

function ChatTable({ models }: { models: InferenceModel[] }) {
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
              <td className="py-3 pr-4">
                <div className="text-[var(--color-ink)]">{m.name}</div>
                <code className="text-xs font-[var(--font-mono)] text-[var(--color-ink-faint)]">
                  {m.id}
                </code>
              </td>
              <td className="py-3 pr-4">
                <Price micro={m.pricePer1kInput} unit="1K tok" />
              </td>
              <td className="py-3 pr-4">
                <Price micro={m.pricePer1kOutput} unit="1K tok" />
              </td>
              <td className="py-3 pr-4 text-xs font-[var(--font-mono)] text-[var(--color-ink-soft)]">
                {m.contextWindow?.toLocaleString() ?? "—"}
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

function ImageTable({ models }: { models: InferenceModel[] }) {
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
                <div className="text-[var(--color-ink)]">{m.name}</div>
                <code className="text-xs font-[var(--font-mono)] text-[var(--color-ink-faint)]">
                  {m.id}
                </code>
              </td>
              <td className="py-3 pr-4">
                <Price micro={m.pricePerImage} unit="image" />
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

  const chat = (data ?? []).filter((m) => m.kind === "chat");
  const image = (data ?? []).filter((m) => m.kind === "image");

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
              Priced per token, split between what you send and what the model writes back.
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
              Priced per generated image, whatever the size or step count.
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
