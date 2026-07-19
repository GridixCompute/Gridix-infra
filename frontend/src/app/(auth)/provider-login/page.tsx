"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Card, CardBody } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { safeNext } from "@/lib/auth/safe-next";

/**
 * Provider sign-in with the agent key.
 *
 * Developers do not sign in here — /login is wallet-only, and a developer key is
 * rejected by the route behind this form. Providers keep a key-based path because
 * the backend has no wallet identity for them yet; when it does, this page goes away.
 */
function ProviderLoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  // `next` is attacker-supplied and acted on right after sign-in (pentest H14).
  const next =
    typeof window === "undefined" ? null : safeNext(params.get("next"), window.location.origin);

  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetch("/api/session/provider", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ apiKey }),
      });
      if (res.ok) {
        router.replace(next && next !== "/dashboard" ? next : "/provider");
        router.refresh();
        return;
      }
      const data = (await res.json().catch(() => ({}))) as { message?: string };
      setError(data.message ?? "That agent key isn't valid.");
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
            Provider sign-in
          </h1>
          <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
            Paste the agent key you saved when you registered your node. It&apos;s stored in a
            secure httpOnly cookie, never exposed to the browser.
          </p>
        </div>
        <form onSubmit={onSubmit} className="space-y-4">
          <Input
            label="Agent key"
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
          Building on GRIDIX instead?{" "}
          <Link href="/login" className="text-[var(--color-signal-bright)] underline">
            Sign in with your wallet
          </Link>{" "}
          ·{" "}
          <Link href="/provider-register" className="text-[var(--color-signal-bright)] underline">
            Run a node
          </Link>
        </p>
      </CardBody>
    </Card>
  );
}

export default function ProviderLoginPage() {
  return (
    <Suspense fallback={null}>
      <ProviderLoginForm />
    </Suspense>
  );
}
