import Link from "next/link";
import { Logo } from "@/components/brand/Logo";
import { Providers } from "@/lib/query/Providers";

/**
 * Centered, focused shell for auth screens. Wrapped in Providers because /login
 * signs in with the wallet and so needs wagmi here, before any session exists.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <Providers>
      <div className="relative flex min-h-dvh flex-col items-center justify-center px-5 py-12">
        <div className="bg-grid absolute inset-0 -z-10 opacity-40" aria-hidden="true" />
        <Link href="/" className="mb-8" aria-label="GRIDIX home">
          <Logo size={32} />
        </Link>
        <div className="w-full max-w-md">{children}</div>
      </div>
    </Providers>
  );
}
