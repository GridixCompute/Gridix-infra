import { describe, it, expect } from "vitest";
import { queryKeys } from "./keys";

describe("queryKeys", () => {
  it("produces stable, structured keys", () => {
    expect(queryKeys.jobs.all).toEqual(["jobs"]);
    expect(queryKeys.jobs.list({ limit: 50 })).toEqual(["jobs", "list", { limit: 50 }]);
    expect(queryKeys.jobs.detail("abc")).toEqual(["jobs", "detail", "abc"]);
    expect(queryKeys.jobs.audit("abc")).toEqual(["jobs", "audit", "abc"]);
  });

  it("distinguishes lists by their filters", () => {
    const a = JSON.stringify(queryKeys.jobs.list({ limit: 50 }));
    const b = JSON.stringify(queryKeys.jobs.list({ limit: 20 }));
    expect(a).not.toBe(b);
  });
});
