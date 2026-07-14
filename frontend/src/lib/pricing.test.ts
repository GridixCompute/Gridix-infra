import { describe, it, expect } from "vitest";
import { estimateCost } from "./pricing";
import { formatUsdc } from "./format/usdc";

describe("estimateCost", () => {
  it("matches the backend model: base 1.0 USDC per cpu-core-minute", () => {
    // 1 cpu, 300s = 5 minutes -> 5.00 compute, +2.5% fee.
    const e = estimateCost({ cpuCores: 1, gpu: false, timeoutSeconds: 300 });
    expect(e.computeBase).toBe(5_000_000n);
    expect(e.feeBase).toBe(125_000n);
    expect(e.totalBase).toBe(5_125_000n);
    expect(formatUsdc(e.computeBase)).toBe("5.00 USDC");
  });

  it("applies the 4x GPU multiplier", () => {
    const cpu = estimateCost({ cpuCores: 2, gpu: false, timeoutSeconds: 600 });
    const gpu = estimateCost({ cpuCores: 2, gpu: true, timeoutSeconds: 600 });
    expect(gpu.computeBase).toBe(cpu.computeBase * 4n);
    expect(gpu.computeBase).toBe(80_000_000n); // 1 * 2 * 4 * 10min
  });

  it("scales linearly with cpu and duration", () => {
    const a = estimateCost({ cpuCores: 4, gpu: false, timeoutSeconds: 1800 });
    expect(a.computeBase).toBe(120_000_000n); // 1 * 4 * 30min
  });

  it("clamps cpu to at least 1 and floors fractional inputs", () => {
    const e = estimateCost({ cpuCores: 0, gpu: false, timeoutSeconds: 60 });
    expect(e.computeBase).toBe(1_000_000n); // treated as 1 cpu * 1 min
  });
});
