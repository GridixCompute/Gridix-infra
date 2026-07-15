import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Middleware does two jobs:
 *
 * 1. Security headers (Sesi 14.5) on EVERY response — CSP, HSTS, and friends.
 *    They live here, not in next.config `headers()`, because that path silently
 *    drops CSP/HSTS on full-route-cache hits; middleware applies uniformly to
 *    static, dynamic, and cached responses.
 * 2. Auth routing (Sesi 4.3 / 11.1): a request to a private area without a
 *    session cookie is redirected to /login; a signed-in principal that lands in
 *    the other role's area is sent to its own home.
 */
const SESSION_COOKIE = "gridix_session";
const ROLE_COOKIE = "gridix_role";
const DEVELOPER_AREAS = ["/dashboard", "/jobs", "/billing", "/settings"];
const PROVIDER_HOME = "/provider";
const DEVELOPER_HOME = "/dashboard";

function matches(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

function rpcOrigin(): string {
  try {
    return new URL(process.env.NEXT_PUBLIC_RPC_URL ?? "https://ethereum-sepolia-rpc.publicnode.com")
      .origin;
  } catch {
    return "https://ethereum-sepolia-rpc.publicnode.com";
  }
}

function withSecurityHeaders(res: NextResponse): NextResponse {
  // Self-contained app: no third-party scripts, all backend traffic proxied
  // same-origin; the only cross-origin connection is the wallet's chain RPC.
  const csp = [
    "default-src 'self'",
    // Next injects inline hydration scripts without a nonce → 'unsafe-inline'.
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src 'self' ${rpcOrigin()} https:`,
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
    "worker-src 'self' blob:",
  ].join("; ");

  const h = res.headers;
  h.set("Content-Security-Policy", csp);
  h.set("X-Content-Type-Options", "nosniff");
  h.set("X-Frame-Options", "DENY");
  h.set("Referrer-Policy", "strict-origin-when-cross-origin");
  h.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  h.set("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload");
  return res;
}

export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  const isProviderArea = matches(pathname, PROVIDER_HOME);
  const isDeveloperArea = DEVELOPER_AREAS.some((p) => matches(pathname, p));

  // Auth routing for private areas.
  if (isProviderArea || isDeveloperArea) {
    if (!req.cookies.has(SESSION_COOKIE)) {
      const loginUrl = new URL("/login", req.url);
      loginUrl.searchParams.set("next", pathname + search);
      return withSecurityHeaders(NextResponse.redirect(loginUrl));
    }
    const role = req.cookies.get(ROLE_COOKIE)?.value;
    if (isProviderArea && role === "developer") {
      return withSecurityHeaders(NextResponse.redirect(new URL(DEVELOPER_HOME, req.url)));
    }
    if (isDeveloperArea && role === "provider") {
      return withSecurityHeaders(NextResponse.redirect(new URL(PROVIDER_HOME, req.url)));
    }
  }

  return withSecurityHeaders(NextResponse.next());
}

export const config = {
  // Run on everything except Next's static assets and public files, so security
  // headers cover all real responses without paying the cost on immutable assets.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|assets/).*)"],
};
