"use client";

import Link from "next/link";
import { useAccount } from "wagmi";
import { Card, CardBody, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { useEscrowBalance } from "@/lib/chain/hooks";

/**
 * First-run onboarding (Session 14.2). Shown to a developer who hasn't run a job
 * yet: a two-step path to their first result — fund escrow, then submit a
 * sample job in one click — so a new user gets there without asking.
 */
export function GettingStarted() {
  const { address, isConnected } = useAccount();
  const escrow = useEscrowBalance(address);
  const funded = isConnected && ((escrow.data as bigint | undefined) ?? 0n) > 0n;

  return (
    <Card className="border-[var(--color-signal-dim)] bg-[var(--color-signal-glow)]">
      <CardBody className="space-y-5">
        <div>
          <CardTitle>Get started in two steps</CardTitle>
          <p className="mt-1 text-sm text-[var(--color-ink-soft)]">
            Fund your escrow, then run a sample job. You&apos;ll have a completed result in minutes.
          </p>
        </div>

        <ol className="space-y-4">
          <Item done={funded} n={1} title="Fund your escrow">
            <p className="text-sm text-[var(--color-ink-soft)]">
              Deposit USDC so the network can run your jobs. On Sepolia testnet today.
            </p>
            <Link href="/billing" className="mt-2 inline-block">
              <Button size="sm" variant={funded ? "ghost" : "primary"}>
                {funded ? "Manage balance" : "Fund escrow"}
              </Button>
            </Link>
          </Item>

          <Item done={false} n={2} title="Run a sample job">
            <p className="text-sm text-[var(--color-ink-soft)]">
              We&apos;ll prefill a tiny public container — submit it as-is to see the full flow.
            </p>
            <Link href="/jobs/new?sample=1" className="mt-2 inline-block">
              <Button size="sm">Try a sample job</Button>
            </Link>
          </Item>
        </ol>

        <p className="text-xs text-[var(--color-ink-faint)]">
          Prefer the command line? The{" "}
          <Link href="/docs" className="text-[var(--color-signal-bright)] underline">
            docs
          </Link>{" "}
          walk through the same flow with curl.
        </p>
      </CardBody>
    </Card>
  );
}

function Item({
  n,
  title,
  done,
  children,
}: {
  n: number;
  title: string;
  done: boolean;
  children: React.ReactNode;
}) {
  return (
    <li className="flex gap-3">
      <span
        className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold ${
          done
            ? "border-[var(--color-success)] bg-[var(--color-success)] text-black"
            : "border-[var(--color-signal-dim)] bg-[var(--color-signal-glow)] text-[var(--color-signal-bright)]"
        }`}
        aria-hidden="true"
      >
        {done ? "✓" : n}
      </span>
      <div>
        <div className="text-sm font-medium text-[var(--color-ink)]">{title}</div>
        {children}
      </div>
    </li>
  );
}
