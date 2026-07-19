import { NextResponse } from "next/server";
import { backendJson } from "@/lib/api/server";
import type { NonceResponse } from "@/lib/api/types";

/**
 * Step one of wallet sign-in: ask the backend for a SIWE challenge.
 *
 * Unauthenticated by design — this is what a caller has before they have a session.
 * The full EIP-4361 message is composed and stored server-side; the page only relays
 * it to the wallet to sign verbatim, so domain and chainId can't be forged here.
 */
export async function GET(req: Request) {
  const address = new URL(req.url).searchParams.get("address")?.trim() ?? "";
  // The backend caps this at 42; reject the oversize case here rather than forwarding
  // a body that can only come back 422.
  if (!address || address.length > 42) {
    return NextResponse.json({ message: "Connect a wallet first." }, { status: 422 });
  }

  const { status, data } = await backendJson<NonceResponse>(
    `/auth/nonce?address=${encodeURIComponent(address)}`,
  );

  if (status < 200 || status >= 300) {
    return NextResponse.json({ message: "Couldn't start sign-in. Try again." }, { status: 502 });
  }

  return NextResponse.json({ nonce: data.nonce, message: data.message });
}
