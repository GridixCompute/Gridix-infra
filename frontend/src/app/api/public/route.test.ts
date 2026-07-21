import { describe, it, expect, vi, beforeEach } from "vitest";

/**
 * The public proxy's path confinement — the security boundary of the whole free tier.
 *
 * `/api/gw` refuses anonymous callers. This one does not, because chat has to work with no
 * account. That makes the `/public/` prefix the ONLY thing standing between an unauthenticated
 * browser request and the rest of the backend: without it, anyone could reach `/v1`, `/jobs`
 * or `/billing` from the page with no session at all, through a proxy that exists to be open.
 *
 * It is one line of string interpolation, which is exactly why it needs a test — it looks
 * like formatting and behaves like authentication.
 */

const backendFetch = vi.fn();
const getSessionKey = vi.fn();

vi.mock("@/lib/api/server", () => ({ backendFetch: (...a: unknown[]) => backendFetch(...a) }));
vi.mock("@/lib/auth/session", () => ({ getSessionKey: () => getSessionKey() }));

async function callGet(segments: string[], url = "http://localhost/api/public/x") {
  const { GET } = await import("./[...path]/route");
  return GET(new Request(url), { params: Promise.resolve({ path: segments }) });
}

beforeEach(() => {
  vi.resetModules();
  backendFetch.mockReset().mockResolvedValue(new Response("{}", { status: 200 }));
  getSessionKey.mockReset().mockResolvedValue(undefined);
});

describe("path confinement", () => {
  it("rewrites every request under /public/", async () => {
    await callGet(["models"]);
    expect(backendFetch).toHaveBeenCalledWith("/public/models", expect.anything());
  });

  it.each([
    [["v1", "chat", "completions"], "/public/v1/chat/completions"],
    [["jobs"], "/public/jobs"],
    [["billing", "summary"], "/public/billing/summary"],
  ])("cannot be steered outside it: %j", async (segments, expected) => {
    // Each of these is a real backend route. Reaching them anonymously is the hole this
    // prefix exists to close, so they must land under /public/ (where they do not exist)
    // rather than at their real paths.
    await callGet(segments as string[]);
    const [path] = backendFetch.mock.calls[0]!;
    expect(path).toBe(expected);
    expect(path.startsWith("/public/")).toBe(true);
  });

  it("refuses traversal segments outright", async () => {
    const res = await callGet(["..", "..", "v1", "chat"]);
    expect(res.status).toBe(400);
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it("encodes segments, so a slash cannot be smuggled in one", async () => {
    await callGet(["images/../../v1"]);
    const [path] = backendFetch.mock.calls[0]!;
    expect(path.startsWith("/public/")).toBe(true);
    expect(path).not.toContain("/v1");
  });
});

describe("session forwarding", () => {
  it("proxies anonymously when there is no session — chat needs no account", async () => {
    getSessionKey.mockResolvedValue(undefined);
    await callGet(["chat"]);
    const [, init] = backendFetch.mock.calls[0]!;
    expect(init.apiKey).toBeUndefined();
  });

  it("forwards the session when there is one — images are wallet-gated", async () => {
    // The key lives in an httpOnly cookie the browser cannot read, so only this proxy can
    // attach it. Without that, the image endpoints would never see a session and would 401
    // a signed-in visitor.
    getSessionKey.mockResolvedValue("grdx_session_key");
    await callGet(["images", "quota"]);
    const [, init] = backendFetch.mock.calls[0]!;
    expect(init.apiKey).toBe("grdx_session_key");
  });
});
