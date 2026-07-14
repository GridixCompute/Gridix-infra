import { describe, it, expect } from "vitest";
import { toApiError, toNetworkError, isApiError, ApiError } from "./errors";

function res(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), { status });
}

describe("toApiError", () => {
  it("maps status codes to distinct kinds", async () => {
    const cases: [number, string][] = [
      [401, "unauthorized"],
      [403, "forbidden"],
      [404, "not_found"],
      [409, "conflict"],
      [422, "validation"],
      [429, "rate_limited"],
      [500, "server"],
      [418, "unknown"],
    ];
    for (const [status, kind] of cases) {
      const e = await toApiError(res(status));
      expect(e.kind).toBe(kind);
      expect(e.status).toBe(status);
      expect(e.message.length).toBeGreaterThan(0);
    }
  });

  it("parses FastAPI 422 detail into per-field errors", async () => {
    const e = await toApiError(
      res(422, {
        detail: [
          { loc: ["body", "image_ref"], msg: "field required" },
          { loc: ["body", "resource_spec", "gpu_vram_mb"], msg: "must be > 0" },
        ],
      }),
    );
    expect(e.kind).toBe("validation");
    expect(e.fieldError("image_ref")).toBe("field required");
    expect(e.fieldError("resource_spec.gpu_vram_mb")).toBe("must be > 0");
    expect(e.fieldError("nope")).toBeUndefined();
  });

  it("uses a string detail as the message", async () => {
    const e = await toApiError(res(403, { detail: "Insufficient balance: deposit more." }));
    expect(e.message).toBe("Insufficient balance: deposit more.");
  });

  it("marks server and rate-limit errors retryable, others not", async () => {
    expect((await toApiError(res(500))).retryable).toBe(true);
    expect((await toApiError(res(429))).retryable).toBe(true);
    expect((await toApiError(res(404))).retryable).toBe(false);
  });
});

describe("toNetworkError", () => {
  it("classifies an abort as a timeout", () => {
    const e = toNetworkError(new DOMException("aborted", "AbortError"));
    expect(e.kind).toBe("network");
    expect(e.message).toMatch(/timed out/i);
    expect(e.retryable).toBe(false);
  });

  it("treats other failures as retryable network errors", () => {
    const e = toNetworkError(new TypeError("Failed to fetch"));
    expect(e.kind).toBe("network");
    expect(e.retryable).toBe(true);
  });
});

describe("isApiError", () => {
  it("narrows ApiError instances", () => {
    expect(isApiError(new ApiError({ kind: "server", status: 500, message: "x" }))).toBe(true);
    expect(isApiError(new Error("plain"))).toBe(false);
  });
});
