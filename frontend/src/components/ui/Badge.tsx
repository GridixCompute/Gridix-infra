import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils/cn";

type Tone = "neutral" | "signal" | "success" | "danger" | "warning" | "info";

const tones: Record<Tone, string> = {
  neutral:
    "bg-[var(--color-panel-raised)] text-[var(--color-ink-soft)] border-[var(--color-hairline-strong)]",
  signal:
    "bg-[var(--color-signal-glow)] text-[var(--color-signal-bright)] border-[var(--color-signal-dim)]",
  success: "bg-[#35c88a1a] text-[var(--color-success)] border-[#35c88a55]",
  danger: "bg-[#ff5c5c1a] text-[var(--color-danger)] border-[#ff5c5c55]",
  warning: "bg-[#ffab3d1a] text-[var(--color-warning)] border-[#ffab3d55]",
  info: "bg-[#4aa3ff1a] text-[var(--color-info)] border-[#4aa3ff55]",
};

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  mono?: boolean;
}

export function Badge({ tone = "neutral", mono, className, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        mono && "tabular font-[var(--font-mono)]",
        tones[tone],
        className,
      )}
      {...props}
    />
  );
}
