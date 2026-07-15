import { describe, it, expect, beforeEach, vi } from "vitest";
import { scrubPII, reportError, track, initObservability, type ObservabilityEvent } from "./report";

describe("scrubPII", () => {
  it("redacts API keys, bearer tokens, addresses, and the session cookie", () => {
    expect(scrubPII("key grdx_AbC123_secret-x here")).toBe("key grdx_[redacted] here");
    expect(scrubPII("Authorization: Bearer grdx_zzz.aaa")).toContain("Bearer [redacted]");
    expect(scrubPII("from 0x2dA408cb2899351eC948b4A3Dd438caA9Ac213e8 now")).toBe(
      "from 0x[redacted] now",
    );
    expect(scrubPII("cookie gridix_session=grdx_live; path=/")).toContain(
      "gridix_session=[redacted]",
    );
  });

  it("leaves ordinary text and short hex (selectors) untouched", () => {
    expect(scrubPII("job completed in 42s")).toBe("job completed in 42s");
    expect(scrubPII("selector 0xa9059cbb")).toBe("selector 0xa9059cbb");
  });
});

describe("reportError / track", () => {
  let events: ObservabilityEvent[];
  beforeEach(() => {
    events = [];
    initObservability((e) => events.push(e));
  });

  it("scrubs the error message, stack, and context before it leaves the browser", () => {
    const err = new Error(
      "failed for grdx_topsecret_key at 0x2dA408cb2899351eC948b4A3Dd438caA9Ac213e8",
    );
    reportError(err, { apiKey: "grdx_another_secret", note: "ok" });

    expect(events).toHaveLength(1);
    const e = events[0]!;
    expect(e.type).toBe("error");
    if (e.type === "error") {
      expect(e.message).not.toContain("topsecret");
      expect(e.message).toContain("grdx_[redacted]");
      expect(e.message).toContain("0x[redacted]");
      expect(e.context?.apiKey).toBe("grdx_[redacted]");
      expect(e.context?.note).toBe("ok");
    }
  });

  it("emits scrubbed funnel events", () => {
    track("first_job_submitted", { image: "ghcr.io/acme/x", key: "grdx_leak" });
    const e = events[0]!;
    expect(e.type).toBe("event");
    if (e.type === "event") {
      expect(e.name).toBe("first_job_submitted");
      expect(e.props?.key).toBe("grdx_[redacted]");
      expect(e.props?.image).toBe("ghcr.io/acme/x");
    }
  });

  it("coerces non-Error throwables", () => {
    const spy = vi.fn();
    initObservability(spy);
    reportError("string failure");
    expect(spy).toHaveBeenCalledOnce();
  });
});
