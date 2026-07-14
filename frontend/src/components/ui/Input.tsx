import { forwardRef, useId } from "react";
import type { InputHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils/cn";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
  error?: string;
  mono?: boolean;
  trailing?: ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, mono, trailing, className, id, ...props },
  ref,
) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const describedBy = error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined;

  return (
    <div className="space-y-1.5">
      {label && (
        <label htmlFor={inputId} className="block text-sm font-medium text-[var(--color-ink-soft)]">
          {label}
        </label>
      )}
      <div className="relative">
        <input
          ref={ref}
          id={inputId}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={cn(
            "h-11 w-full rounded-[var(--radius-sm)] border bg-[var(--color-abyss)] px-3 text-sm text-[var(--color-ink)] " +
              "placeholder:text-[var(--color-ink-disabled)] transition-colors " +
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-signal)]",
            mono && "font-[var(--font-mono)]",
            error
              ? "border-[var(--color-danger)]"
              : "border-[var(--color-hairline-strong)] focus:border-[var(--color-signal-dim)]",
            trailing ? "pr-11" : "",
            className,
          )}
          {...props}
        />
        {trailing && (
          <span className="absolute inset-y-0 right-2 flex items-center">{trailing}</span>
        )}
      </div>
      {error ? (
        <p id={`${inputId}-error`} className="text-xs text-[var(--color-danger)]">
          {error}
        </p>
      ) : hint ? (
        <p id={`${inputId}-hint`} className="text-xs text-[var(--color-ink-faint)]">
          {hint}
        </p>
      ) : null}
    </div>
  );
});
