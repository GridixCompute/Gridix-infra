"use client";

import { useState } from "react";
import { Card, CardBody, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { CodeBlock } from "@/components/provider/CodeBlock";

/**
 * Add the provider capability to the signed-in wallet address.
 *
 * This replaces the deleted /provider-register page, and the difference is not cosmetic.
 * That page created an account and signed the browser in AS the provider using the agent
 * key it had just minted — a machine credential opening a human session, attached to a
 * Provider row with no wallet address that no wallet session could ever reach again.
 *
 * Here there is no new account and no new session: the operator is already signed in with
 * their wallet, and this adds a capability to that same identity. The key it returns is for
 * their NODE, which is why it is shown once, labelled as machine credentials, and never
 * written to a cookie — the operator signs in with the wallet they already used.
 */

type Props = {
  /** Called once the operator confirms they have saved the key. */
  onComplete: () => void;
};

export function BecomeProvider({ onComplete }: Props) {
  const [name, setName] = useState("");
  const [region, setRegion] = useState("");
  const [agentKey, setAgentKey] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetch("/api/providers/onboard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, region }),
      });
      const data = (await res.json()) as { apiKey?: string; message?: string };
      if (!res.ok || !data.apiKey) {
        setError(data.message ?? "Couldn't register your node. Try again.");
        return;
      }
      setAgentKey(data.apiKey);
    } catch {
      setError("Can't reach GRIDIX. Check your connection and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (agentKey) {
    return (
      <Card>
        <CardBody className="space-y-4">
          <CardTitle className="!mt-0">Save your node&apos;s agent key</CardTitle>
          <p className="text-sm text-[var(--color-ink-soft)]">
            This is shown <strong>once</strong>. It goes in your node&apos;s environment as{" "}
            <code className="text-xs font-[var(--font-mono)]">GRIDIX_PROVIDER_KEY</code>.
          </p>

          {/* The distinction the old flow blurred, said plainly. */}
          <p
            role="note"
            className="rounded-[var(--radius-sm)] border border-[var(--color-warning)] bg-[var(--color-panel-raised)] px-3 py-2 text-sm text-[var(--color-ink-soft)]"
          >
            <strong>These are credentials for your node, not for signing in.</strong> You sign in
            with the wallet you just used — this key only lets a machine you own join the network.
            Anyone who has it can serve work as you, so treat it like a private key.
          </p>

          <CodeBlock code={agentKey} />

          <label className="flex items-start gap-2 text-sm text-[var(--color-ink-soft)]">
            <input
              type="checkbox"
              checked={saved}
              onChange={(e) => setSaved(e.target.checked)}
              className="mt-0.5"
            />
            <span>I&apos;ve saved this key somewhere safe.</span>
          </label>

          <Button disabled={!saved} onClick={onComplete}>
            Continue to setup
          </Button>
        </CardBody>
      </Card>
    );
  }

  return (
    <Card>
      <CardBody className="space-y-4">
        <CardTitle className="!mt-0">Run a node</CardTitle>
        <p className="text-sm text-[var(--color-ink-soft)]">
          Register the wallet you&apos;re signed in with as a provider. Earnings and reputation
          attach to this address — the same one you use as a developer.
        </p>

        <form onSubmit={onSubmit} className="space-y-4">
          <Input
            label="Node name"
            hint="How your node appears to the network."
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Input
            label="Region"
            hint="Optional. Where the hardware lives, e.g. eu-west."
            value={region}
            onChange={(e) => setRegion(e.target.value)}
          />

          {error && (
            <p role="alert" className="text-sm text-[var(--color-danger)]">
              {error}
            </p>
          )}

          <Button type="submit" disabled={submitting || !name.trim()}>
            {submitting ? "Registering…" : "Register node"}
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}
