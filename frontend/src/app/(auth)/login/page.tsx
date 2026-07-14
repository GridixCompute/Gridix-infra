"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Card, CardBody } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") ?? "/dashboard";

  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ apiKey }),
      });
      if (res.ok) {
        router.replace(next);
        router.refresh();
        return;
      }
      const data = (await res.json().catch(() => ({}))) as { message?: string };
      setError(data.message ?? "That API key isn't valid.");
    } catch {
      setError("Can't reach GRIDIX. Check your connection and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardBody className="space-y-5">
        <div>
          <h1 className="text-xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
            Sign in
          </h1>
          <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
            Paste your developer API key. It&apos;s stored in a secure httpOnly cookie — never
            exposed to the browser.
          </p>
        </div>
        <form onSubmit={onSubmit} className="space-y-4">
          <Input
            label="API key"
            type="password"
            placeholder="grdx_…"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            error={error ?? undefined}
            mono
            autoFocus
            required
          />
          <Button type="submit" className="w-full" loading={submitting} disabled={!apiKey.trim()}>
            Sign in
          </Button>
        </form>
        <p className="text-center text-sm text-[var(--color-ink-faint)]">
          No account yet?{" "}
          <Link href="/register" className="text-[var(--color-signal-bright)] hover:underline">
            Create one
          </Link>
        </p>
      </CardBody>
    </Card>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
