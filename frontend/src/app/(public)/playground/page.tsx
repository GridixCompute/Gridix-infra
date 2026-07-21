import type { Metadata } from "next";
import { FreePlayground } from "@/components/playground/FreePlayground";

export const metadata: Metadata = {
  title: "Playground — GRIDIX",
  description: "Chat with a model running on the GRIDIX network. Free, no account needed.",
};

export default function PlaygroundPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
          Playground
        </h1>
        <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
          Chat is free and needs no account. Image generation is free too — 5 a day — and needs a
          connected wallet so the allowance can be counted.
        </p>
      </div>
      <FreePlayground />
    </div>
  );
}
