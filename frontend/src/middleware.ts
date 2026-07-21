import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Middleware does two jobs:
 *
 * 1. Security headers (Session 14.5) on EVERY response — CSP, HSTS, and friends.
 *    They live here, not in next.config `headers()`, because that path silently
 *    drops CSP/HSTS on full-route-cache hits; middleware applies uniformly to
 *    static, dynamic, and cached responses.
 * 2. Auth routing: a request to a private area without a session cookie is
 *    redirected to /login — the only way in, for everyone. Inside the provider
 *    console, an address that is not a provider yet is sent to onboarding.
 *
 * The old model gave developers and providers separate sign-in pages and bounced
 * each out of the other's area, because a principal was one role or the other. One
 * address is now one identity that may hold BOTH capabilities, so bouncing is wrong:
 * it would lock a developer who also runs a node out of half their own account.
 */
const SESSION_COOKIE = "gridix_session";
const CAPS_COOKIE = "gridix_caps";
const DEVELOPER_AREAS = ["/dashboard", "/playground", "/models", "/jobs", "/billing", "/settings"];
const PROVIDER_HOME = "/provider";
/** Where an address without the provider capability goes to acquire it. */
const PROVIDER_ONBOARDING = "/provider/onboarding";

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

function buildCsp(nonce: string): string {
  // Self-contained app: no third-party scripts, all backend traffic proxied
  // same-origin; the only cross-origin connection is the wallet's chain RPC.
  //
  // C2/H13: NO script 'unsafe-inline'. Inline scripts run only with the per-request
  // nonce; 'strict-dynamic' lets those trusted scripts load the app's chunks. So an
  // injected <script> from an XSS can't execute — it has no valid nonce.
  //
  // `next dev` evaluates its bundled modules through eval(), so without 'unsafe-eval' the
  // dev server's own scripts are blocked and the app never hydrates — the page renders its
  // SSR output and then sits there, dead, which reads as a broken feature rather than a
  // blocked script. Production builds don't eval, so the allowance is scoped to dev and the
  // shipped policy stays exactly as strict as C2/H13 made it.
  const devEval = process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : "";
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${devEval}`,
    // Styles still need inline (Tailwind/next-font inject <style>); style injection
    // can't steal a session cookie the way script execution can.
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
}

function setSecurityHeaders(res: NextResponse, csp: string): NextResponse {
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
  // Fresh nonce per request; Next applies it to its own inline scripts when it sees
  // the nonce in the request's CSP header.
  const nonce = btoa(crypto.randomUUID());
  const csp = buildCsp(nonce);

  const isProviderArea = matches(pathname, PROVIDER_HOME);
  const isDeveloperArea = DEVELOPER_AREAS.some((p) => matches(pathname, p));

  // Auth routing for private areas (redirects carry no HTML, so no nonce needed).
  if (isProviderArea || isDeveloperArea) {
    if (!req.cookies.has(SESSION_COOKIE)) {
      // One way in, for everyone. There is no second sign-in page to choose between.
      const loginUrl = new URL("/login", req.url);
      loginUrl.searchParams.set("next", pathname + search);
      return setSecurityHeaders(NextResponse.redirect(loginUrl), csp);
    }

    // Developer areas need nothing beyond a session: wallet sign-in resolves-or-creates a
    // developer, so every signed-in address has that capability by construction.
    if (isProviderArea && !matches(pathname, PROVIDER_ONBOARDING)) {
      const caps = req.cookies.get(CAPS_COOKIE)?.value?.split(",") ?? [];
      if (!caps.includes("provider")) {
        // Signed in, but this address owns no Provider record yet. Onboarding is the way
        // to acquire one, so send them there rather than to the dashboard — a bare bounce
        // would read as "you are not allowed" when the truth is "not yet".
        return setSecurityHeaders(
          NextResponse.redirect(new URL(PROVIDER_ONBOARDING, req.url)),
          csp,
        );
      }
    }
  }

  // Forward the nonce + CSP on the REQUEST so Next nonces its hydration scripts.
  const requestHeaders = new Headers(req.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("content-security-policy", csp);
  const res = NextResponse.next({ request: { headers: requestHeaders } });
  return setSecurityHeaders(res, csp);
}

export const config = {
  // Run on everything except Next's static assets and public files, so security
  // headers cover all real responses without paying the cost on immutable assets.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|assets/).*)"],
};
