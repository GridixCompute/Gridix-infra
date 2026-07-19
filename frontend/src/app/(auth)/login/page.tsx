"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAccount, useSignMessage } from "wagmi";
import { Card, CardBody } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ConnectWallet } from "@/components/chain/ConnectWallet";
import { safeNext } from "@/lib/auth/safe-next";

/** EIP-1193 rejection, i.e. the user clicked "reject" in the wallet. */
function isUserRejection(err: unknown): boolean {
  return typeof err === "object" && err !== null && (err as { code?: number }).code === 4001;
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  // Never redirect anywhere but our own origin: `next` is attacker-supplied and is acted on
  // right after a successful sign-in (pentest H14). Unsafe values fall back to the default.
  const next =
    typeof window === "undefined" ? null : safeNext(params.get("next"), window.location.origin);

  const { address, isConnected } = useAccount();
  const { signMessageAsync } = useSignMessage();
  const [error, setError] = useState<string | null>(null);
  const [signing, setSigning] = useState(false);

  async function onSignIn() {
    if (!address) return;
    setError(null);
    setSigning(true);
    try {
      // 1. Challenge. The message text is composed by the backend, never here.
      const nonceRes = await fetch(`/api/session/nonce?address=${encodeURIComponent(address)}`);
      const challenge = (await nonceRes.json().catch(() => ({}))) as {
        nonce?: string;
        message?: string;
      };
      if (!nonceRes.ok || !challenge.nonce || !challenge.message) {
        setError("Couldn't start sign-in. Try again.");
        return;
      }

      // 2. The wallet signs it verbatim.
      const signature = await signMessageAsync({ message: challenge.message });

      // 3. Exchange the signature for a session cookie.
      const res = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address, nonce: challenge.nonce, signature }),
      });
      if (res.ok) {
        router.replace(next ?? "/dashboard");
        router.refresh();
        return;
      }
      const data = (await res.json().catch(() => ({}))) as { message?: string };
      setError(data.message ?? "Couldn't sign you in. Try again.");
    } catch (err) {
      setError(
        isUserRejection(err)
          ? "You declined the signature. Sign the message to continue."
          : "Can't reach GRIDIX. Check your connection and try again.",
      );
    } finally {
      setSigning(false);
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
            Connect your wallet and sign a message to prove it&apos;s yours. No password, no API
            key. First time here? Signing in creates your account — the same address you deposit
            USDC from.
          </p>
        </div>

        <div className="flex justify-center">
          <ConnectWallet />
        </div>

        {isConnected && (
          <Button className="w-full" onClick={onSignIn} loading={signing}>
            Sign in with wallet
          </Button>
        )}

        {error && (
          <p role="alert" className="text-sm text-[var(--color-danger)]">
            {error}
          </p>
        )}

        <p className="text-center text-sm text-[var(--color-ink-faint)]">
          Running a node?{" "}
          <Link href="/provider-login" className="text-[var(--color-signal-bright)] underline">
            Provider sign-in
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
