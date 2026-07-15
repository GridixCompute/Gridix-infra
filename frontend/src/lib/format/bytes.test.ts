import { describe, it, expect } from "vitest";
import { formatBytes } from "./bytes";

describe("formatBytes", () => {
  it("formats binary units with no decimals for whole bytes", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
  });

  it("scales into KiB/MiB/GiB", () => {
    expect(formatBytes(1024)).toBe("1.0 KiB");
    expect(formatBytes(1536)).toBe("1.5 KiB");
    expect(formatBytes(1024 * 1024)).toBe("1.0 MiB");
    expect(formatBytes(3 * 1024 ** 3)).toBe("3.0 GiB");
  });

  it("guards against zero and invalid input", () => {
    expect(formatBytes(-5)).toBe("0 B");
    expect(formatBytes(NaN)).toBe("0 B");
  });

  it("respects a custom fraction precision", () => {
    expect(formatBytes(1536, 2)).toBe("1.50 KiB");
  });
});
