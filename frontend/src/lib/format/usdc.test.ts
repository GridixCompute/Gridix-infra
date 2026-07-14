import { describe, it, expect } from "vitest";
import { parseUsdc, formatUsdc, toBaseUnits, formatUsdcAmount, USDC_DECIMALS } from "./usdc";

describe("parseUsdc", () => {
  it("parses whole and fractional amounts to 6-decimal base units", () => {
    expect(parseUsdc("1")).toBe(1_000_000n);
    expect(parseUsdc("12.5")).toBe(12_500_000n);
    expect(parseUsdc("0.000001")).toBe(1n); // smallest unit
    expect(parseUsdc("0")).toBe(0n);
    expect(parseUsdc(".5")).toBe(500_000n);
  });

  it("keeps full precision on large amounts (no float drift)", () => {
    expect(parseUsdc("1000000")).toBe(1_000_000_000_000n);
    expect(parseUsdc("123456.789012")).toBe(123_456_789_012n);
  });

  it("rejects more than 6 decimal places", () => {
    expect(() => parseUsdc("1.0000001")).toThrow(/6 decimal/);
  });

  it("rejects non-numeric input", () => {
    for (const bad of ["", ".", "abc", "1.2.3", "-5", "1e6", " "]) {
      expect(() => parseUsdc(bad)).toThrow();
    }
  });

  it("uses 6 decimals, not 18", () => {
    expect(USDC_DECIMALS).toBe(6);
  });
});

describe("formatUsdc", () => {
  it("formats base units exactly", () => {
    expect(formatUsdc(12_500_000n)).toBe("12.50 USDC");
    expect(formatUsdc(5_000_000n)).toBe("5.00 USDC");
    expect(formatUsdc(1n)).toBe("0.000001 USDC");
    expect(formatUsdc(0n)).toBe("0.00 USDC");
  });

  it("groups thousands and shows a minus for negatives", () => {
    expect(formatUsdc(1_000_000_000_000n)).toBe("1,000,000.00 USDC");
    expect(formatUsdc(-5_000_000n)).toBe("-5.00 USDC");
  });

  it("honors symbol and minFractionDigits options", () => {
    expect(formatUsdc(5_000_000n, { symbol: false })).toBe("5.00");
    expect(formatUsdc(125_000n, { minFractionDigits: 0 })).toBe("0.125 USDC");
  });

  it("round-trips through parse", () => {
    for (const v of ["0.01", "999.999999", "42", "0.000001"]) {
      expect(formatUsdc(parseUsdc(v), { symbol: false, minFractionDigits: 0 })).toBe(v);
    }
  });
});

describe("toBaseUnits / formatUsdcAmount", () => {
  it("coerces number, string, and bigint API amounts", () => {
    expect(toBaseUnits(12.5)).toBe(12_500_000n);
    expect(toBaseUnits("3")).toBe(3_000_000n);
    expect(toBaseUnits(86.4)).toBe(86_400_000n);
    expect(toBaseUnits(7n)).toBe(7n);
  });

  it("formats an API decimal amount", () => {
    expect(formatUsdcAmount(86.4)).toBe("86.40 USDC");
    expect(formatUsdcAmount("33.6")).toBe("33.60 USDC");
  });
});
