import { Providers } from "@/lib/query/Providers";
import { RealtimeProvider } from "@/lib/realtime/RealtimeProvider";
import { AppHeader } from "@/components/app/AppHeader";
import { OfflineBanner } from "@/components/app/OfflineBanner";

/** Authenticated app shell — data provider + chrome for every protected page. */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <Providers>
      <RealtimeProvider>
        <div className="flex min-h-dvh flex-col">
          <OfflineBanner />
          <AppHeader />
          <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-8">{children}</main>
        </div>
      </RealtimeProvider>
    </Providers>
  );
}
