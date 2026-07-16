import { describe, it, expect } from "vitest";
import { safeNext } from "./safe-next";

const ORIGIN = "https://app.gridix.dev";

describe("safeNext — pentest H14 (open redirect after login)", () => {
  it("rejects the absolute off-site URL from the finding", () => {
    // /login?next=https://evil.com/phish — the phishing hand-off, post-credentials.
    expect(safeNext("https://evil.com/phish", ORIGIN)).toBeNull();
  });

  it("rejects protocol-relative targets that still start with a slash", () => {
    // The case a naive startsWith("/") guard lets through.
    expect(safeNext("//evil.com", ORIGIN)).toBeNull();
    expect(safeNext("//evil.com/phish", ORIGIN)).toBeNull();
  });

  it("rejects backslash forms browsers treat as protocol-relative", () => {
    expect(safeNext("/\\evil.com", ORIGIN)).toBeNull();
    expect(safeNext("/\\/evil.com", ORIGIN)).toBeNull();
  });

  it("rejects non-http schemes", () => {
    expect(safeNext("javascript:alert(document.cookie)", ORIGIN)).toBeNull();
    expect(safeNext("data:text/html,<script>alert(1)</script>", ORIGIN)).toBeNull();
  });

  it("rejects a different origin even when it looks like ours", () => {
    expect(safeNext("https://app.gridix.dev.evil.com/x", ORIGIN)).toBeNull();
    expect(safeNext("http://app.gridix.dev/x", ORIGIN)).toBeNull(); // scheme downgrade
  });

  it("rejects empty / missing input", () => {
    expect(safeNext(null, ORIGIN)).toBeNull();
    expect(safeNext(undefined, ORIGIN)).toBeNull();
    expect(safeNext("", ORIGIN)).toBeNull();
    expect(safeNext("dashboard", ORIGIN)).toBeNull(); // relative, no leading slash
  });

  it("keeps honest same-origin paths intact", () => {
    expect(safeNext("/dashboard", ORIGIN)).toBe("/dashboard");
    expect(safeNext("/jobs/abc-123", ORIGIN)).toBe("/jobs/abc-123");
    expect(safeNext("/jobs?status=running", ORIGIN)).toBe("/jobs?status=running");
    expect(safeNext("/jobs#logs", ORIGIN)).toBe("/jobs#logs");
    expect(safeNext("/provider?tab=earnings#top", ORIGIN)).toBe("/provider?tab=earnings#top");
  });

  it("normalises traversal back to a path on this origin", () => {
    // Cannot escape the origin — resolves to a same-origin path, which is safe.
    expect(safeNext("/../../etc/passwd", ORIGIN)).toBe("/etc/passwd");
  });
});
