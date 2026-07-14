import { describe, it, expect } from "vitest";
import { relativeTime, formatDuration } from "./time";

describe("relativeTime", () => {
  const now = Date.parse("2026-07-14T12:00:00Z");

  it("formats past and future relative to an injected now", () => {
    expect(relativeTime("2026-07-14T11:59:30Z", now)).toMatch(/30 seconds ago/);
    expect(relativeTime("2026-07-14T11:00:00Z", now)).toMatch(/1 hour ago/);
    expect(relativeTime("2026-07-14T14:00:00Z", now)).toMatch(/in 2 hours/);
  });

  it("returns a dash for invalid input", () => {
    expect(relativeTime("not-a-date", now)).toBe("—");
  });
});

describe("formatDuration", () => {
  it("formats hours, minutes, seconds", () => {
    expect(formatDuration("2026-07-14T12:00:00Z", "2026-07-14T12:00:05Z")).toBe("5s");
    expect(formatDuration("2026-07-14T12:00:00Z", "2026-07-14T12:02:14Z")).toBe("2m 14s");
    expect(formatDuration("2026-07-14T12:00:00Z", "2026-07-14T13:05:30Z")).toBe("1h 5m 30s");
  });

  it("returns a dash when the range is invalid or negative", () => {
    expect(formatDuration("2026-07-14T12:00:05Z", "2026-07-14T12:00:00Z")).toBe("—");
    expect(formatDuration("bad", "2026-07-14T12:00:00Z")).toBe("—");
  });
});
