"use client";

import { useState } from "react";
import { useAccount } from "wagmi";
import { waitForTransactionReceipt, writeContract } from "wagmi/actions";
import { wagmiConfig, contracts } from "@/lib/chain/config";
import { escrowAbi, erc20Abi } from "@/lib/chain/abis";
import { useAllowance, useEscrowBalance, useWalletUsdc } from "@/lib/chain/hooks";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { TxStatus, type TxState } from "@/components/domain/TxStatus";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { parseUsdc } from "@/lib/format/usdc";
import { track } from "@/lib/observability/report";

type Mode = "deposit" | "withdraw";

/**
 * Deposit (approve → deposit, Session 6.2) or withdraw (Session 6.4), with an honest
 * tx lifecycle (Session 5.4): signing → pending (hash + explorer) → confirmed.
 * Never shows success before the chain confirms.
 */
export function DepositWithdraw({ mode }: { mode: Mode }) {
  const { address } = useAccount();
  const [amount, setAmount] = useState("");
  const [tx, setTx] = useState<TxState>("idle");
  const [step, setStep] = useState<"approve" | "deposit" | "withdraw" | null>(null);
  const [hash, setHash] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);

  const allowance = useAllowance(address);
  const escrow = useEscrowBalance(address);
  const walletUsdc = useWalletUsdc(address);

  const busy = tx === "signing" || tx === "pending";

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

  const cap = mode === "deposit" ? walletUsdc.data : escrow.data;
  if (base != null && cap != null && base > cap) {
    parseError =
      mode === "deposit"
        ? "You don't have that much USDC in your wallet."
        : "You can't withdraw more than your escrow balance.";
  }

  async function run() {
    if (base == null || parseError || !address) return;
    setError(null);
    try {
      if (mode === "deposit") {
        const allow = (allowance.data as bigint | undefined) ?? 0n;
        if (allow < base) {
          setStep("approve");
          setTx("signing");
          const approveHash = await writeContract(wagmiConfig, {
            address: contracts.usdc,
            abi: erc20Abi,
            functionName: "approve",
            args: [contracts.escrow, base],
          });
          setHash(approveHash);
          setTx("pending");
          await waitForTransactionReceipt(wagmiConfig, { hash: approveHash });
        }
        setStep("deposit");
        setTx("signing");
        const depHash = await writeContract(wagmiConfig, {
          address: contracts.escrow,
          abi: escrowAbi,
          functionName: "deposit",
          args: [base],
        });
        setHash(depHash);
        setTx("pending");
        await waitForTransactionReceipt(wagmiConfig, { hash: depHash });
      } else {
        setStep("withdraw");
        setTx("signing");
        const wHash = await writeContract(wagmiConfig, {
          address: contracts.escrow,
          abi: escrowAbi,
          functionName: "withdraw",
          args: [base],
        });
        setHash(wHash);
        setTx("pending");
        await waitForTransactionReceipt(wagmiConfig, { hash: wHash });
      }
      setTx("confirmed");
      if (mode === "deposit") track("escrow_deposited");
      setStep(null);
      setAmount("");
      void escrow.refetch();
      void walletUsdc.refetch();
      void allowance.refetch();
    } catch (e) {
      setTx("failed");
      setStep(null);
      const msg = e instanceof Error ? e.message : "Transaction failed.";
      // Common, friendlier cases.
      setError(
        /user rejected|denied/i.test(msg)
          ? "You rejected the transaction in your wallet."
          : /insufficient funds/i.test(msg)
            ? "Not enough ETH to pay for gas."
            : msg.split("\n")[0]!,
      );
    }
  }

  const label = mode === "deposit" ? "Deposit USDC" : "Withdraw USDC";

  return (
    <div className="space-y-4">
      <Input
        label={mode === "deposit" ? "Amount to deposit" : "Amount to withdraw"}
        placeholder="0.00"
        inputMode="decimal"
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
        error={parseError ?? undefined}
        mono
        disabled={busy}
        hint={
          mode === "deposit"
            ? cap != null
              ? undefined
              : "Connect to see your wallet balance."
            : undefined
        }
        trailing={
          cap != null ? (
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

      {mode === "deposit" && (
        <p className="text-xs text-[var(--color-ink-faint)]">
          {allowance.data != null && base != null && (allowance.data as bigint) < base
            ? "This needs two transactions: approve USDC, then deposit."
            : "One transaction — your allowance already covers this."}
        </p>
      )}

      <Button className="w-full" onClick={run} loading={busy} disabled={!base || !!parseError}>
        {busy && step === "approve"
          ? "Approving…"
          : busy && step === "deposit"
            ? "Depositing…"
            : busy && step === "withdraw"
              ? "Withdrawing…"
              : label}
      </Button>

      {tx !== "idle" && (
        <div className="flex flex-col gap-1">
          <TxStatus state={tx} hash={hash} />
          {tx === "confirmed" && (
            <span className="text-sm text-[var(--color-success)]">
              Done. Your escrow balance is now{" "}
              {escrow.data != null ? <USDCAmount base={escrow.data as bigint} /> : "updated"}.
            </span>
          )}
          {error && <span className="text-sm text-[var(--color-danger)]">{error}</span>}
        </div>
      )}
    </div>
  );
}
