import type { Metadata } from "next";
import { ModelsTable } from "@/components/playground/ModelsTable";

export const metadata: Metadata = {
  title: "Models — GRIDIX",
  description: "Models served on the GRIDIX network, and what each costs per use.",
};

export default function ModelsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
          Models
        </h1>
        <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
          What the network serves right now, and what each costs. Prices are in USDC.
        </p>
      </div>
      <ModelsTable />
    </div>
  );
}
