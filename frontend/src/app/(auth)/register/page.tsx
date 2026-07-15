"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Card, CardBody } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetch("/api/developers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const data = (await res.json()) as { apiKey?: string; message?: string };
      if (!res.ok || !data.apiKey) {
        setError(data.message ?? "Couldn't create your account. Try again.");
        return;
      }
      setApiKey(data.apiKey);
    } catch {
      setError("Can't reach GRIDIX. Check your connection and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  // Step 2: the key is shown exactly once.
  if (apiKey) {
    return (
      <Card>
        <CardBody className="space-y-5">
          <div>
            <h1 className="text-xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
              Save your API key
            </h1>
            <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
              This is the only time it will be shown. Store it somewhere safe — it authenticates
              every request and the GRIDIX agent CLI.
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
            I have saved my API key somewhere secure.
          </label>
          <Button className="w-full" disabled={!saved} onClick={() => router.replace("/dashboard")}>
            Continue to dashboard
          </Button>
        </CardBody>
      </Card>
    );
  }

  // Step 1: name.
  return (
    <Card>
      <CardBody className="space-y-5">
        <div>
          <h1 className="text-xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
            Create your account
          </h1>
          <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
            One field to start. You&apos;ll get an API key and land on your dashboard.
          </p>
        </div>
        <form onSubmit={onSubmit} className="space-y-4">
          <Input
            label="Account name"
            placeholder="e.g. Acme AI"
            value={name}
            onChange={(e) => setName(e.target.value)}
            error={error ?? undefined}
            autoFocus
            required
          />
          <Button type="submit" className="w-full" loading={submitting} disabled={!name.trim()}>
            Create account
          </Button>
        </form>
        <p className="text-center text-sm text-[var(--color-ink-faint)]">
          Already have a key?{" "}
          <Link href="/login" className="text-[var(--color-signal-bright)] underline">
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
