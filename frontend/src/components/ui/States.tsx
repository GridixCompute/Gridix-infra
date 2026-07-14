import type { ReactNode } from "react";
import { Button } from "./Button";

/** Empty state = a call to action, never a dead "no data" (Sesi 2.5 / 13.1). */
export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description: string;
  action?: { label: string; onClick?: () => void; href?: string };
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      {icon && <div className="text-[var(--color-signal-dim)]">{icon}</div>}
      <h3 className="text-lg font-[var(--font-display)] font-semibold text-[var(--color-ink)]">
        {title}
      </h3>
      <p className="max-w-sm text-sm text-[var(--color-ink-faint)]">{description}</p>
      {action &&
        (action.href ? (
          <a href={action.href}>
            <Button className="mt-1">{action.label}</Button>
          </a>
        ) : (
          <Button className="mt-1" onClick={action.onClick}>
            {action.label}
          </Button>
        ))}
    </div>
  );
}

/** Honest error state — explains what failed and offers a retry (Sesi 3.5). */
export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <div
        className="flex h-10 w-10 items-center justify-center rounded-full border border-[#ff5c5c55] bg-[#ff5c5c1a] text-[var(--color-danger)]"
        aria-hidden="true"
      >
        !
      </div>
      <h3 className="text-lg font-[var(--font-display)] font-semibold text-[var(--color-ink)]">
        {title}
      </h3>
      <p className="max-w-sm text-sm text-[var(--color-ink-faint)]">{message}</p>
      {onRetry && (
        <Button variant="secondary" className="mt-1" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
