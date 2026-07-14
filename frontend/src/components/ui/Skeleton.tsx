import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils/cn";

/** Content-shaped loading placeholder — never a bare spinner (Sesi 13.1). */
export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-[var(--radius-sm)] bg-[var(--color-panel-raised)]",
        className,
      )}
      aria-hidden="true"
      {...props}
    />
  );
}
