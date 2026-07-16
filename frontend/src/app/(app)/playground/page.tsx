import type { Metadata } from "next";
import { PlaygroundShell } from "@/components/playground/PlaygroundShell";

export const metadata: Metadata = {
  title: "Playground — GRIDIX",
  description: "Call a model on the GRIDIX network and pay per use in USDC.",
};

export default function PlaygroundPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-[var(--font-display)] text-2xl font-bold text-[var(--color-ink)]">
          Playground
        </h1>
        <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
          Send a prompt to a model running on the network. You pay per token, in USDC.
        </p>
      </div>
      <PlaygroundShell />
    </div>
  );
}
