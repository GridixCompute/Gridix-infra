"use client";

import { useState } from "react";
import { cn } from "@/lib/utils/cn";

/** A copyable shell/code snippet used on the onboarding page. */
export function CodeBlock({ code, className }: { code: string; className?: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard blocked */
    }
  }

  return (
    <div
      className={cn(
        "group relative overflow-x-auto rounded-[var(--radius-md)] border border-[var(--color-hairline)] bg-[var(--color-void)]",
        className,
      )}
    >
      <button
        type="button"
        onClick={copy}
        className="absolute top-2 right-2 rounded-[var(--radius-sm)] border border-[var(--color-hairline-strong)] bg-[var(--color-panel)] px-2 py-1 text-xs text-[var(--color-ink-soft)] opacity-0 transition-opacity group-hover:opacity-100 hover:text-[var(--color-ink)] focus:opacity-100"
        aria-label="Copy to clipboard"
      >
        {copied ? "Copied" : "Copy"}
      </button>
      <pre className="px-4 py-3 text-sm">
        <code className="font-[var(--font-mono)] whitespace-pre text-[var(--color-ink-soft)]">
          {code}
        </code>
      </pre>
    </div>
  );
}
