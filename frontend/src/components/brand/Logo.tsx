import Image from "next/image";
import { cn } from "@/lib/utils/cn";

/** GRIDIX mark + wordmark. The mark is the hexagonal G from the brand assets. */
export function Logo({
  size = 28,
  withWordmark = true,
  className,
}: {
  size?: number;
  withWordmark?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <Image
        src="/assets/logo.png"
        alt="GRIDIX"
        width={size}
        height={size}
        priority
        className="drop-shadow-[0_0_12px_var(--color-signal-glow)]"
      />
      {withWordmark && (
        <span className="font-[var(--font-display)] text-lg font-bold tracking-[0.14em] text-[var(--color-ink)]">
          GRIDIX
        </span>
      )}
    </span>
  );
}
