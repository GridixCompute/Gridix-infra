import type { ReactNode } from "react";
import { cn } from "@/lib/utils/cn";

/** A labelled metric tile used across the provider console. */
export function ProviderStat({
  label,
  value,
  hint,
  className,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-md)] border border-[var(--color-hairline)] bg-[var(--color-panel)] px-4 py-3.5",
        className,
      )}
    >
      <div className="text-xs font-medium tracking-wide text-[var(--color-ink-faint)] uppercase">
        {label}
      </div>
      <div className="mt-1.5 text-lg font-[var(--font-display)] font-semibold text-[var(--color-ink)]">
        {value}
      </div>
      {hint != null && <div className="mt-0.5 text-xs text-[var(--color-ink-faint)]">{hint}</div>}
    </div>
  );
}
