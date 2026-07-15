"use client";

import { useState } from "react";
import Link from "next/link";
import { useAccount } from "wagmi";
import { writeContract } from "wagmi/actions";
import { wagmiConfig, contracts } from "@/lib/chain/config";
import { stakingAbi, erc20Abi } from "@/lib/chain/abis";
import { useWalletUsdc } from "@/lib/chain/hooks";
import {
  useProviderStake,
  useMinStake,
  useUnstaking,
  useStakeDispute,
  useStakeAllowance,
} from "@/lib/chain/stakingHooks";
import { useChainAction } from "@/lib/chain/useChainAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { TxStatus } from "@/components/domain/TxStatus";
import { ProviderStat } from "@/components/provider/ProviderStat";
import { parseUsdc } from "@/lib/format/usdc";

type Mode = "stake" | "unstake";

export function StakePanel() {
  const { address, isConnected } = useAccount();
  const stake = useProviderStake(address);
  const minStake = useMinStake();
  const unstaking = useUnstaking(address);
  const dispute = useStakeDispute(address);
  const wallet = useWalletUsdc(address);
  const allowance = useStakeAllowance(address);
  const { tx, hash, error, busy, run } = useChainAction();

  const [mode, setMode] = useState<Mode>("stake");
  const [amount, setAmount] = useState("");

  const active = (stake.data as bigint | undefined) ?? 0n;
  const min = (minStake.data as bigint | undefined) ?? 0n;
  const meetsMin = active >= min && min > 0n;
  const [coolAmount, coolUnlockAt] = (unstaking.data as readonly [bigint, bigint] | undefined) ?? [
    0n,
    0n,
  ];
  const [disputedAmount] = (dispute.data as readonly [bigint, string, boolean] | undefined) ?? [
    0n,
    "0x",
    false,
  ];

  // Parse + validate the amount for the current mode.
  let parseError: string | null = null;
  let base: bigint | null = null;
  if (amount.trim()) {
    try {
      base = parseUsdc(amount);
      if (base <= 0n) parseError = "Enter an amount greater than zero.";
    } catch (e) {
      parseError = e instanceof Error ? e.message : "Invalid amount.";
    }
  }
  const cap = mode === "stake" ? ((wallet.data as bigint | undefined) ?? null) : active;
  if (base != null && cap != null && base > cap) {
    parseError =
      mode === "stake"
        ? "You don't have that much USDC in your wallet."
        : "You can't unstake more than your active stake.";
  }

  async function submit() {
    if (base == null || parseError || !address) return;
    const amt = base;
    await run(async (send) => {
      if (mode === "stake") {
        const allow = (allowance.data as bigint | undefined) ?? 0n;
        if (allow < amt) {
          await send(() =>
            writeContract(wagmiConfig, {
              address: contracts.usdc,
              abi: erc20Abi,
              functionName: "approve",
              args: [contracts.staking, amt],
            }),
          );
        }
        await send(() =>
          writeContract(wagmiConfig, {
            address: contracts.staking,
            abi: stakingAbi,
            functionName: "stake",
            args: [amt],
          }),
        );
      } else {
        await send(() =>
          writeContract(wagmiConfig, {
            address: contracts.staking,
            abi: stakingAbi,
            functionName: "unstake",
            args: [amt],
          }),
        );
      }
      setAmount("");
      void stake.refetch();
      void wallet.refetch();
      void allowance.refetch();
      void unstaking.refetch();
    });
  }

  async function completeUnstake() {
    await run(async (send) => {
      await send(() =>
        writeContract(wagmiConfig, {
          address: contracts.staking,
          abi: stakingAbi,
          functionName: "completeUnstake",
        }),
      );
      void stake.refetch();
      void wallet.refetch();
      void unstaking.refetch();
    });
  }

  const unlocked = coolAmount > 0n && Date.now() / 1000 >= Number(coolUnlockAt);

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2">
        <ProviderStat
          label="Active stake"
          value={isConnected ? <USDCAmount base={active} /> : "—"}
          hint={
            isConnected ? (
              meetsMin ? (
                <Badge tone="success">Meets minimum</Badge>
              ) : (
                <Badge tone="warning">Below minimum</Badge>
              )
            ) : (
              "connect your wallet"
            )
          }
        />
        <ProviderStat
          label="Minimum stake"
          value={<USDCAmount base={min} />}
          hint="to receive jobs"
        />
      </div>

      {isConnected && !meetsMin && (
        <p className="rounded-[var(--radius-sm)] border border-[#ffab3d55] bg-[#ffab3d12] px-3 py-2 text-sm text-[var(--color-ink-soft)]">
          You need at least <USDCAmount base={min} /> staked before the scheduler will assign you
          jobs. Stake below to start earning.
        </p>
      )}

      {/* Stake / unstake */}
      <div className="space-y-3">
        <div className="inline-flex rounded-[var(--radius-sm)] border border-[var(--color-hairline-strong)] p-0.5">
          {(["stake", "unstake"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => {
                setMode(m);
                setAmount("");
              }}
              className={`rounded-[calc(var(--radius-sm)-2px)] px-3 py-1 text-sm capitalize transition-colors ${
                mode === m
                  ? "bg-[var(--color-panel-raised)] text-[var(--color-ink)]"
                  : "text-[var(--color-ink-faint)] hover:text-[var(--color-ink)]"
              }`}
            >
              {m}
            </button>
          ))}
        </div>

        <Input
          label={mode === "stake" ? "Amount to stake" : "Amount to unstake"}
          placeholder="0.00"
          inputMode="decimal"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          error={parseError ?? undefined}
          mono
          disabled={busy || !isConnected}
          trailing={
            cap != null && cap > 0n ? (
              <button
                type="button"
                className="text-xs text-[var(--color-signal-bright)] hover:underline"
                onClick={() => setAmount((Number(cap) / 1_000_000).toString())}
                disabled={busy}
              >
                MAX
              </button>
            ) : undefined
          }
        />

        {mode === "unstake" && (
          <p className="text-xs text-[var(--color-ink-faint)]">
            Unstaking starts a cooldown before the funds are withdrawable — your stake stays
            slashable until it completes.
          </p>
        )}

        <Button
          className="w-full"
          onClick={submit}
          loading={busy}
          disabled={!isConnected || !base || !!parseError}
        >
          {mode === "stake" ? "Stake USDC" : "Begin unstake"}
        </Button>
      </div>

      {/* Cooling down */}
      {coolAmount > 0n && (
        <div className="rounded-[var(--radius-md)] border border-[var(--color-hairline)] bg-[var(--color-panel)] px-4 py-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-medium text-[var(--color-ink)]">
                Cooling down: <USDCAmount base={coolAmount} />
              </div>
              <div className="mt-0.5 text-xs text-[var(--color-ink-faint)]">
                {unlocked
                  ? "Cooldown complete — you can withdraw it now."
                  : `Unlocks ${new Date(Number(coolUnlockAt) * 1000).toLocaleString()}`}
              </div>
            </div>
            <Button size="sm" onClick={completeUnstake} loading={busy} disabled={!unlocked}>
              Complete
            </Button>
          </div>
        </div>
      )}

      {/* Disputed / held */}
      {disputedAmount > 0n && (
        <div className="rounded-[var(--radius-md)] border border-[#ff5c5c55] bg-[#ff5c5c12] px-4 py-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-[var(--color-ink-soft)]">
              <USDCAmount base={disputedAmount} /> held under a slash dispute.
            </span>
            <Link
              href="/provider/disputes"
              className="text-[var(--color-signal-bright)] hover:underline"
            >
              Review →
            </Link>
          </div>
        </div>
      )}

      {tx !== "idle" && (
        <div className="flex flex-col gap-1">
          <TxStatus state={tx} hash={hash} />
          {error && <span className="text-sm text-[var(--color-danger)]">{error}</span>}
        </div>
      )}
    </div>
  );
}
