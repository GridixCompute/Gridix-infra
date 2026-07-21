import { Providers } from "@/lib/query/Providers";
import { SiteHeader } from "@/components/marketing/SiteHeader";
import { SiteFooter } from "@/components/marketing/SiteFooter";

/**
 * Public app shell — for pages anyone can open without an account.
 *
 * Deliberately NOT the `(app)` layout: that one carries the signed-in chrome (AppHeader,
 * the realtime job feed, the connectivity banner) and every piece of it assumes a session.
 * A visitor with no account should see the marketing chrome they arrived through, not a
 * dashboard header with nothing behind it.
 *
 * `Providers` is still needed — react-query and wagmi live there, and the playground uses
 * both: wagmi so the image tab can offer a wallet connection, react-query for its fetches.
 */
export default function PublicAppLayout({ children }: { children: React.ReactNode }) {
  return (
    <Providers>
      <div className="flex min-h-dvh flex-col">
        <SiteHeader />
        <main className="mx-auto w-full max-w-5xl flex-1 px-5 py-8">{children}</main>
        <SiteFooter />
      </div>
    </Providers>
  );
}
