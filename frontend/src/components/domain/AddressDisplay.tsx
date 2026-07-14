"use client";

import { useState } from "react";
import { truncateHex, explorerAddressUrl, explorerTxUrl } from "@/lib/format/address";
import { cn } from "@/lib/utils/cn";

/**
 * Renders a 0x address or tx hash: truncated, monospace, copy button, and a
 * link to the block explorer (Sesi 2.4). Used everywhere — no ad-hoc hex.
 */
export function AddressDisplay({
  value,
  kind = "address",
  className,
  lead,
  tail,
}: {
  value: string;
  kind?: "address" | "tx";
  className?: string;
  lead?: number;
  tail?: number;
}) {
  const [copied, setCopied] = useState(false);
  const href = kind === "tx" ? explorerTxUrl(value) : explorerAddressUrl(value);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard blocked — no-op */
    }
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-sm font-[var(--font-mono)] text-[var(--color-ink-soft)]",
        className,
      )}
    >
      <a
        href={href}
        target="_blank"
        rel="noreferrer noopener"
        className="tabular hover:text-[var(--color-signal-bright)] hover:underline"
        title={value}
      >
        {truncateHex(value, lead, tail)}
      </a>
      <button
        type="button"
        onClick={copy}
        aria-label={copied ? "Copied" : "Copy to clipboard"}
        className="text-[var(--color-ink-faint)] transition-colors hover:text-[var(--color-ink)]"
      >
        {copied ? <CheckIcon /> : <CopyIcon />}
      </button>
    </span>
  );
}

function CopyIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2" stroke="currentColor" strokeWidth="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}
function CheckIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M20 6 9 17l-5-5"
        stroke="var(--color-signal)"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
