import Link from "next/link";
import { Logo } from "@/components/brand/Logo";

export function SiteFooter() {
  return (
    <footer className="border-t border-[var(--color-hairline)] bg-[var(--color-abyss)]">
      <div className="mx-auto grid max-w-6xl gap-10 px-5 py-14 md:grid-cols-[1.5fr_1fr_1fr_1fr]">
        <div className="space-y-4">
          <Logo />
          <p className="max-w-xs text-sm text-[var(--color-ink-faint)]">
            Decentralized compute for the next generation of AI. Built for the future.
          </p>
        </div>
        <FooterCol
          title="Product"
          links={[
            { label: "Submit a job", href: "/jobs/new" },
            { label: "Pricing", href: "/docs#pricing" },
            { label: "Run a node", href: "/provider-register" },
          ]}
        />
        <FooterCol
          title="Developers"
          links={[
            { label: "Documentation", href: "/docs" },
            { label: "Quickstart", href: "/docs#quickstart" },
            { label: "API reference", href: "/docs#api" },
          ]}
        />
        <FooterCol
          title="Network"
          links={[
            { label: "FAQ", href: "/docs#faq" },
            { label: "On-chain contracts", href: "/#proof" },
          ]}
        />
      </div>
      <div className="border-t border-[var(--color-hairline)]">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-2 px-5 py-5 text-xs text-[var(--color-ink-faint)] sm:flex-row">
          <span>© {new Date().getFullYear()} GRIDIX. All rights reserved.</span>
          <span className="font-[var(--font-mono)]">Sepolia testnet · settlement on-chain</span>
        </div>
      </div>
    </footer>
  );
}

function FooterCol({ title, links }: { title: string; links: { label: string; href: string }[] }) {
  return (
    <div className="space-y-3">
      <h4 className="text-xs font-semibold tracking-wider text-[var(--color-ink-faint)] uppercase">
        {title}
      </h4>
      <ul className="space-y-2">
        {links.map((l) => (
          <li key={l.href}>
            <Link
              href={l.href}
              className="text-sm text-[var(--color-ink-soft)] transition-colors hover:text-[var(--color-signal-bright)]"
            >
              {l.label}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
