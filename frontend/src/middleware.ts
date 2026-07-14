import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Protected routes (Sesi 4.3). A request to a private area without a session
 * cookie is redirected to /login with a `next` param, never a blank/error page.
 */
const SESSION_COOKIE = "gridix_session";
const PROTECTED = ["/dashboard", "/jobs", "/billing", "/settings"];

export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  const isProtected = PROTECTED.some((p) => pathname === p || pathname.startsWith(`${p}/`));
  if (!isProtected) return NextResponse.next();

  const hasSession = req.cookies.has(SESSION_COOKIE);
  if (hasSession) return NextResponse.next();

  const loginUrl = new URL("/login", req.url);
  loginUrl.searchParams.set("next", pathname + search);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/dashboard/:path*", "/jobs/:path*", "/billing/:path*", "/settings/:path*"],
};
