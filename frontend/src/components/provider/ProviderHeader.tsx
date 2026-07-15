"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/Button";
import { useSession } from "@/lib/hooks/useSession";
import { useProviderMe } from "@/lib/hooks/useProvider";
import { agentConnection } from "@/lib/provider/connection";
import { cn } from "@/lib/utils/cn";

const NAV = [
  { label: "Overview", href: "/provider" },
  { label: "Hardware", href: "/provider/hardware" },
  { label: "Earnings", href: "/provider/earnings" },
  { label: "Disputes", href: "/provider/disputes" },
  { label: "History", href: "/provider/history" },
];

export function ProviderHeader() {
  const pathname = usePathname();
  const { name, logout } = useSession();
  const { data: provider } = useProviderMe();
  const conn = agentConnection(provider);

  return (
    <header className="sticky top-0 z-40 border-b border-[var(--color-hairline)] bg-[var(--color-void)]/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
        <div className="flex items-center gap-8">
          <Link
            href="/provider"
            aria-label="GRIDIX provider console"
            className="flex items-center gap-2"
          >
            <Logo size={26} />
            <span className="hidden text-xs font-[var(--font-mono)] text-[var(--color-ink-faint)] sm:inline">
              / provider
            </span>
          </Link>
          <nav className="hidden items-center gap-1 md:flex" aria-label="Primary">
            {NAV.map((item) => {
              const active =
                item.href === "/provider"
                  ? pathname === "/provider"
                  : pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "rounded-[var(--radius-sm)] px-3 py-1.5 text-sm transition-colors",
                    active
                      ? "bg-[var(--color-panel)] text-[var(--color-ink)]"
                      : "text-[var(--color-ink-soft)] hover:text-[var(--color-ink)]",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <span
            className="hidden items-center gap-1.5 text-xs text-[var(--color-ink-faint)] sm:inline-flex"
            title={conn.title}
          >
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                conn.online
                  ? "animate-pulse-dot bg-[var(--color-success)]"
                  : "bg-[var(--color-ink-disabled)]",
              )}
              aria-hidden="true"
            />
            {conn.label}
          </span>
          {name && (
            <span className="hidden text-sm text-[var(--color-ink-faint)] sm:inline">{name}</span>
          )}
          <Button variant="ghost" size="sm" onClick={logout}>
            Sign out
          </Button>
        </div>
      </div>
    </header>
  );
}
