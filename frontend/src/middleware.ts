import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Protected routes (Sesi 4.3 / 11.1). A request to a private area without a
 * session cookie is redirected to /login, never a blank/error page. Beyond
 * presence, we route by role: the developer app lives under /dashboard, /jobs,
 * /billing, /settings; the provider console under /provider. A signed-in
 * principal that lands in the other role's area is sent to its own home.
 */
const SESSION_COOKIE = "gridix_session";
const ROLE_COOKIE = "gridix_role";
const DEVELOPER_AREAS = ["/dashboard", "/jobs", "/billing", "/settings"];
const PROVIDER_HOME = "/provider";
const DEVELOPER_HOME = "/dashboard";

function matches(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  const isProviderArea = matches(pathname, PROVIDER_HOME);
  const isDeveloperArea = DEVELOPER_AREAS.some((p) => matches(pathname, p));
  if (!isProviderArea && !isDeveloperArea) return NextResponse.next();

  if (!req.cookies.has(SESSION_COOKIE)) {
    const loginUrl = new URL("/login", req.url);
    loginUrl.searchParams.set("next", pathname + search);
    return NextResponse.redirect(loginUrl);
  }

  // Signed in — keep each role in its own console.
  const role = req.cookies.get(ROLE_COOKIE)?.value;
  if (isProviderArea && role === "developer") {
    return NextResponse.redirect(new URL(DEVELOPER_HOME, req.url));
  }
  if (isDeveloperArea && role === "provider") {
    return NextResponse.redirect(new URL(PROVIDER_HOME, req.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/jobs/:path*",
    "/billing/:path*",
    "/settings/:path*",
    "/provider/:path*",
  ],
};
