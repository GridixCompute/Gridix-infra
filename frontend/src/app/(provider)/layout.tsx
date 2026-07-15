import { Providers } from "@/lib/query/Providers";
import { ProviderHeader } from "@/components/provider/ProviderHeader";
import { OfflineBanner } from "@/components/app/OfflineBanner";

/** Provider console shell (Sesi 11) — data provider + chrome for the supply side. */
export default function ProviderLayout({ children }: { children: React.ReactNode }) {
  return (
    <Providers>
      <div className="flex min-h-dvh flex-col">
        <OfflineBanner />
        <ProviderHeader />
        <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-8">{children}</main>
      </div>
    </Providers>
  );
}
