"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Card, CardBody } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { safeNext } from "@/lib/auth/safe-next";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  // Never redirect anywhere but our own origin: `next` is attacker-supplied and is acted on
  // right after a successful sign-in (pentest H14). Unsafe values fall back to the default.
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
      const res = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ apiKey }),
      });
      if (res.ok) {
        const data = (await res.json().catch(() => ({}))) as { role?: string };
        // Honour an explicit redirect target; otherwise send each role home.
        const dest =
          next && next !== "/dashboard"
            ? next
            : data.role === "provider"
              ? "/provider"
              : "/dashboard";
        router.replace(dest);
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
            Paste your developer or provider API key — we detect which. It&apos;s stored in a secure
            httpOnly cookie, never exposed to the browser.
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
          <Link href="/register" className="text-[var(--color-signal-bright)] underline">
            Create one
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

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
