"use client";

import { relativeTime, absoluteTime } from "@/lib/format/time";
import { cn } from "@/lib/utils/cn";

/** Relative time by default; absolute on hover via native title (Session 2.4). */
export function Timestamp({ iso, className }: { iso: string; className?: string }) {
  return (
    <time
      dateTime={iso}
      title={absoluteTime(iso)}
      className={cn("text-[var(--color-ink-faint)]", className)}
    >
      {relativeTime(iso)}
    </time>
  );
}
