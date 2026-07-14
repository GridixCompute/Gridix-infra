import { NextResponse } from "next/server";
import { backendJson } from "@/lib/api/server";
import { setSession } from "@/lib/auth/session";
import type { RegisteredPrincipal } from "@/lib/api/types";

/**
 * Register a developer (Sesi 4.1). Forwards to the backend, then logs the user
 * in by setting the httpOnly session cookie. The api_key is returned to the
 * page ONCE for the user to copy — after that it only lives in the cookie.
 */
export async function POST(req: Request) {
  let name = "";
  try {
    const body = (await req.json()) as { name?: string };
    name = body.name ?? "";
  } catch {
    /* fall through to validation */
  }
  if (!name || !name.trim()) {
    return NextResponse.json({ message: "Enter a name for your account." }, { status: 422 });
  }

  const { status, data } = await backendJson<RegisteredPrincipal>("/developers", {
    method: "POST",
    json: { name: name.trim() },
  });

  if (status < 200 || status >= 300) {
    return NextResponse.json({ message: "Couldn't create your account. Try again." }, { status });
  }

  await setSession(data.api_key, data.name);
  // Return the key once so the page can show it. Not persisted anywhere else.
  return NextResponse.json({ id: data.id, name: data.name, apiKey: data.api_key });
}
