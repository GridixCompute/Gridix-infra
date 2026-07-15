"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Card, CardBody } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

/**
 * Provider registration (Sesi 11.1). Creates a provider account and reveals the
 * agent API key exactly once — the operator pastes it into their node's
 * environment (GRIDIX_API_KEY) during onboarding.
 */
export default function ProviderRegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [region, setRegion] = useState("");
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetch("/api/providers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, region }),
      });
      const data = (await res.json()) as { apiKey?: string; message?: string };
      if (!res.ok || !data.apiKey) {
        setError(data.message ?? "Couldn't create your provider. Try again.");
        return;
      }
      setApiKey(data.apiKey);
    } catch {
      setError("Can't reach GRIDIX. Check your connection and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  // Step 2: the agent key is shown exactly once.
  if (apiKey) {
    return (
      <Card>
        <CardBody className="space-y-5">
          <div>
            <h1 className="text-xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
              Save your agent key
            </h1>
            <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
              This is the only time it will be shown. Your node&apos;s agent authenticates with it
              as <code className="font-[var(--font-mono)]">GRIDIX_API_KEY</code> — the onboarding
              page walks you through the install.
            </p>
          </div>
          <div className="flex items-start justify-between gap-3 rounded-[var(--radius-sm)] border border-[var(--color-signal-dim)] bg-[var(--color-signal-glow)] px-3 py-3">
            <code className="text-sm font-[var(--font-mono)] break-all text-[var(--color-signal-bright)]">
              {apiKey}
            </code>
            <CopyButton value={apiKey} />
          </div>
          <label className="flex items-start gap-2.5 text-sm text-[var(--color-ink-soft)]">
            <input
              type="checkbox"
              checked={saved}
              onChange={(e) => setSaved(e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-[var(--color-signal)]"
            />
            I have saved my agent key somewhere secure.
          </label>
          <Button
            className="w-full"
            disabled={!saved}
            onClick={() => router.replace("/provider/onboarding")}
          >
            Continue to onboarding
          </Button>
        </CardBody>
      </Card>
    );
  }

  // Step 1: name + optional region.
  return (
    <Card>
      <CardBody className="space-y-5">
        <div>
          <h1 className="text-xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
            Run a GRIDIX node
          </h1>
          <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
            Register your provider to earn USDC for compute. You&apos;ll get an agent key and
            step-by-step setup.
          </p>
        </div>
        <form onSubmit={onSubmit} className="space-y-4">
          <Input
            label="Provider name"
            placeholder="e.g. Aurora GPU Farm"
            value={name}
            onChange={(e) => setName(e.target.value)}
            error={error ?? undefined}
            autoFocus
            required
          />
          <Input
            label="Region (optional)"
            placeholder="e.g. eu-central"
            value={region}
            onChange={(e) => setRegion(e.target.value)}
          />
          <Button type="submit" className="w-full" loading={submitting} disabled={!name.trim()}>
            Create provider
          </Button>
        </form>
        <p className="text-center text-sm text-[var(--color-ink-faint)]">
          Already have a key?{" "}
          <Link href="/login" className="text-[var(--color-signal-bright)] hover:underline">
            Sign in
          </Link>
        </p>
      </CardBody>
    </Card>
  );
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      type="button"
      variant="secondary"
      size="sm"
      className="shrink-0"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1400);
        } catch {
          /* clipboard blocked */
        }
      }}
    >
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}
