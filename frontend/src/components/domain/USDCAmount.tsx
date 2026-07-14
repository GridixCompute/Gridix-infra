import { formatUsdc, formatUsdcAmount } from "@/lib/format/usdc";
import { cn } from "@/lib/utils/cn";

/**
 * The single way to display money in GRIDIX (Sesi 2.4 / 6.6). Always 6-decimal
 * exact, tabular figures, monospace. Pass either base units (bigint) or an
 * API decimal amount (number | string).
 */
export function USDCAmount({
  amount,
  base,
  symbol = true,
  minFractionDigits = 2,
  tone = "default",
  className,
}: {
  amount?: number | string;
  base?: bigint;
  symbol?: boolean;
  minFractionDigits?: number;
  tone?: "default" | "signal" | "muted" | "credit" | "debit";
  className?: string;
}) {
  const text =
    base !== undefined
      ? formatUsdc(base, { symbol, minFractionDigits })
      : formatUsdcAmount(amount ?? 0, { symbol, minFractionDigits });

  const tones: Record<string, string> = {
    default: "text-[var(--color-ink)]",
    signal: "text-[var(--color-signal-bright)]",
    muted: "text-[var(--color-ink-faint)]",
    credit: "text-[var(--color-success)]",
    debit: "text-[var(--color-ink)]",
  };

  return (
    <span className={cn("font-[var(--font-mono)] tabular font-medium", tones[tone], className)}>
      {text}
    </span>
  );
}
