import { describe, it, expect } from "vitest";
import { truncateHex, explorerAddressUrl, explorerTxUrl } from "./address";

describe("truncateHex", () => {
  it("truncates long 0x values, keeps short ones", () => {
    const addr = "0xd93076eb67ab21ae068c0ad7a6256ca6ba58f733";
    expect(truncateHex(addr)).toBe("0xd930…f733");
    expect(truncateHex(addr, 10, 6)).toBe("0xd93076eb…58f733");
    expect(truncateHex("0x1234")).toBe("0x1234"); // too short to truncate
    expect(truncateHex("not-hex")).toBe("not-hex"); // non-0x untouched
  });
});

describe("explorer urls", () => {
  it("builds Sepolia explorer links by default", () => {
    expect(explorerAddressUrl("0xabc")).toBe("https://sepolia.etherscan.io/address/0xabc");
    expect(explorerTxUrl("0xdef")).toBe("https://sepolia.etherscan.io/tx/0xdef");
  });
});
