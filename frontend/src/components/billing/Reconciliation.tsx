"use client";

import { Card, CardBody, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { useBillingSummary } from "@/lib/hooks/useBilling";
import { toBaseUnits } from "@/lib/format/usdc";

/**
 * On-chain vs off-chain reconciliation (Session 10.5). The on-chain escrow balance
 * must cover what the off-chain ledger says is held; the ledger's own groups
 * must balance. Any divergence is surfaced loudly — the backend alerts on it and
 * the UI must not stay silent.
 */
export function Reconciliation({ escrowBase }: { escrowBase: bigint | null }) {
  const { data } = useBillingSummary();
  if (!data) return null;

  const heldBase = toBaseUnits(data.total_held);
  const connected = escrowBase != null;
  const undercollateralised = connected && escrowBase < heldBase;
  const availableBase = connected && escrowBase > heldBase ? escrowBase - heldBase : 0n;

  const ok = data.balanced && !undercollateralised;

  return (
    <Card className={ok ? undefined : "border-[#ff5c5c55] bg-[#ff5c5c10]"}>
      <CardBody className="space-y-3">
        <div className="flex items-center justify-between">
          <CardTitle className="!mt-0">Reconciliation</CardTitle>
          <Badge tone={ok ? "success" : "danger"}>
            {!data.balanced
              ? "Ledger imbalance"
              : undercollateralised
                ? "Under-collateralised"
                : "Reconciled"}
          </Badge>
        </div>

        <dl className="grid gap-3 sm:grid-cols-3">
          <Row
            label="On-chain escrow"
            value={connected ? <USDCAmount base={escrowBase} /> : "Connect wallet"}
          />
          <Row label="Off-chain held" value={<USDCAmount amount={data.total_held} />} />
          <Row
            label="Available"
            value={connected ? <USDCAmount base={availableBase} tone="signal" /> : "—"}
          />
        </dl>

        {!data.balanced && (
          <p className="text-sm text-[var(--color-danger)]">
            The ledger has an unbalanced transaction group (debits ≠ credits). This is a backend
            invariant violation — contact support; don&apos;t rely on these figures until it clears.
          </p>
        )}
        {undercollateralised && (
          <p className="text-sm text-[var(--color-danger)]">
            On-chain escrow is below what the ledger reports as held. New jobs may be rejected until
            you deposit.
          </p>
        )}
        {ok && (
          <p className="text-xs text-[var(--color-ink-faint)]">
            {connected
              ? "On-chain escrow covers everything held off-chain, and every ledger group balances."
              : "Every ledger group balances. Connect your wallet to compare against on-chain escrow."}
          </p>
        )}
      </CardBody>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs tracking-wide text-[var(--color-ink-faint)] uppercase">{label}</dt>
      <dd className="mt-1 text-lg">{value}</dd>
    </div>
  );
}
