"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/Button";
import { useSession } from "@/lib/hooks/useSession";
import { useRealtime } from "@/lib/realtime/RealtimeProvider";
import { cn } from "@/lib/utils/cn";

const NAV = [
  { label: "Dashboard", href: "/dashboard" },
  { label: "Jobs", href: "/jobs" },
  { label: "Billing", href: "/billing" },
];

export function AppHeader() {
  const pathname = usePathname();
  const { name, logout } = useSession();
  const { connected } = useRealtime();

  return (
    <header className="sticky top-0 z-40 border-b border-[var(--color-hairline)] bg-[var(--color-void)]/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
        <div className="flex items-center gap-8">
          <Link href="/dashboard" aria-label="GRIDIX dashboard">
            <Logo size={26} />
          </Link>
          <nav className="hidden items-center gap-1 md:flex" aria-label="Primary">
            {NAV.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
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
            title={connected ? "Live updates connected" : "Reconnecting — using polling"}
          >
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                connected
                  ? "animate-pulse-dot bg-[var(--color-success)]"
                  : "bg-[var(--color-ink-disabled)]",
              )}
              aria-hidden="true"
            />
            {connected ? "Live" : "Polling"}
          </span>
          <Link href="/jobs/new" className="hidden sm:block">
            <Button size="sm">New job</Button>
          </Link>
          {name && (
            <span className="hidden text-sm text-[var(--color-ink-faint)] sm:inline">{name}</span>
          )}
          <Link href="/settings">
            <Button variant="ghost" size="sm">
              Settings
            </Button>
          </Link>
          <Button variant="ghost" size="sm" onClick={logout}>
            Sign out
          </Button>
        </div>
      </div>
    </header>
  );
}
