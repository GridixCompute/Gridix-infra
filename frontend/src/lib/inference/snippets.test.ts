import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderSnippet, toCurl, toPython, toTypeScript } from "./snippets";
import type { ImageGenerationRequest } from "./contract";

/**
 * The code shown must be the request actually sent — same path, same bytes.
 *
 * The key test drives the real client against a stubbed fetch, captures the body it sent, and
 * asserts the curl snippet embeds exactly that. A snippet built from a re-typed lookalike
 * would pass a shape-check and fail this.
 *
 * The fixture is typed as the GENERATED `ImageGenerationRequest`, which is what makes this
 * test worth anything now: it previously carried `size` and `steps`, fields the API does not
 * accept, and asserted that the snippet faithfully reproduced them. It was a green test
 * pinning a request the backend would have rejected.
 */

const BASE = "https://api.gridix.dev";

const REQ: ImageGenerationRequest = {
  model: "sdxl-turbo",
  prompt: "a wireframe globe",
  seed: 42,
  n: 1,
  data_tier: "public",
};

describe("snippets carry the request the client really sends", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    // Force the real (non-mock) path so we capture a genuine outbound request.
    vi.stubEnv("NEXT_PUBLIC_INFERENCE_MOCK", "false");
    vi.resetModules();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("curl embeds byte-for-byte what generateImage POSTs", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          created: 0,
          data: [{ url: "https://cdn.gridix.dev/img/1.png" }],
          model: "sdxl-turbo",
          cost_usdc: "0.010000",
          provider_id: "00000000-0000-0000-0000-000000000000",
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );

    const { generateImage: realGenerate } = await import("./client");
    await realGenerate(REQ);

    const sentBody = fetchMock.mock.calls[0]?.[1]?.body as string;
    expect(sentBody).toBeTruthy();

    const snippet = toCurl(BASE, "/v1/images/generations", REQ);
    // The exact payload, not merely an equivalent object.
    expect(snippet).toContain(`-d '${sentBody}'`);
  });

  it("targets the same path the client calls", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          created: 0,
          data: [{ url: "https://cdn.gridix.dev/img/1.png" }],
          model: "sdxl-turbo",
          cost_usdc: "0.010000",
          provider_id: "00000000-0000-0000-0000-000000000000",
        }),
        { status: 200 },
      ),
    );
    const { generateImage: realGenerate } = await import("./client");
    await realGenerate(REQ);

    const url = fetchMock.mock.calls[0]?.[0] as string;
    expect(url).toContain("/v1/images/generations");
    expect(toCurl(BASE, "/v1/images/generations", REQ)).toContain("/v1/images/generations");
  });
});

describe("snippet rendering", () => {
  it("never prints the caller's key", () => {
    for (const lang of ["curl", "typescript", "python"] as const) {
      const out = renderSnippet(lang, BASE, "/v1/images/generations", REQ);
      expect(out).not.toContain("grdx_");
      expect(out.toLowerCase()).toContain("gridix_api_key"); // a placeholder they must fill
    }
  });

  it("emits Python literals, not JSON ones", () => {
    const out = toPython(BASE, "/v1/chat/completions", { stream: true, seed: null, echo: false });
    expect(out).toContain("True");
    expect(out).toContain("None");
    expect(out).toContain("False");
    expect(out).not.toMatch(/\btrue\b/);
    expect(out).not.toMatch(/\bnull\b/);
  });

  it("keeps the params the user tuned", () => {
    const ts = toTypeScript(BASE, "/v1/images/generations", REQ);
    expect(ts).toContain('"seed": 42');
    expect(ts).toContain('"model": "sdxl-turbo"');
    expect(ts).toContain('"n": 1');
  });

  it("points at the configured API host", () => {
    expect(toCurl(BASE, "/v1/models", {})).toContain(`${BASE}/v1/models`);
  });
});
