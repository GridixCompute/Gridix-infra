import { describe, it, expect } from "vitest";
import { groupByJob, toCsv } from "./ledger";
import type { BillingLedgerEntry } from "@/lib/api/types";

// One completed job: hold 10 → settle (provider 5.85 + protocol 0.15) → refund 4 → data 0.5.
const JOB = "11111111-1111-1111-1111-111111111111";
function entry(p: Partial<BillingLedgerEntry>): BillingLedgerEntry {
  return {
    id: crypto.randomUUID?.() ?? String(Math.random()),
    entry_group: "g",
    job_id: JOB,
    account: "developer",
    direction: "debit",
    amount: 0,
    reason: "escrow_hold",
    created_at: "2026-07-15T10:00:00Z",
    ...p,
  };
}

const LEDGER: BillingLedgerEntry[] = [
  entry({
    reason: "escrow_hold",
    account: "developer",
    direction: "debit",
    amount: 10,
    entry_group: "g1",
    created_at: "2026-07-15T10:00:00Z",
  }),
  entry({
    reason: "escrow_hold",
    account: "escrow",
    direction: "credit",
    amount: 10,
    entry_group: "g1",
  }),
  entry({
    reason: "settle",
    account: "escrow",
    direction: "debit",
    amount: 6,
    entry_group: "g2",
    created_at: "2026-07-15T11:00:00Z",
  }),
  entry({
    reason: "settle",
    account: "provider",
    direction: "credit",
    amount: 5.85,
    entry_group: "g2",
  }),
  entry({
    reason: "settle",
    account: "protocol",
    direction: "credit",
    amount: 0.15,
    entry_group: "g2",
  }),
  entry({ reason: "refund", account: "escrow", direction: "debit", amount: 4, entry_group: "g3" }),
  entry({
    reason: "refund",
    account: "developer",
    direction: "credit",
    amount: 4,
    entry_group: "g3",
  }),
  entry({
    reason: "data_cost",
    account: "developer",
    direction: "debit",
    amount: 0.5,
    entry_group: "g4",
    created_at: "2026-07-15T11:30:00Z",
  }),
  entry({
    reason: "data_cost",
    account: "protocol",
    direction: "credit",
    amount: 0.5,
    entry_group: "g4",
  }),
];

describe("groupByJob", () => {
  it("computes a breakdown that sums exactly to the total charged", () => {
    const [g] = groupByJob(LEDGER);
    expect(g!.jobId).toBe(JOB);
    expect(g!.providerPaid).toBe(5.85);
    expect(g!.protocolFee).toBe(0.15);
    expect(g!.dataCost).toBe(0.5);
    expect(g!.escrowed).toBe(10);
    expect(g!.refunded).toBe(4);
    // provider + fee + data == total charged (== cost_final)
    expect(g!.totalCharged).toBeCloseTo(6.5, 10);
    expect(g!.providerPaid + g!.protocolFee + g!.dataCost).toBeCloseTo(g!.totalCharged, 10);
  });

  it("uses the newest leg as the group timestamp", () => {
    const [g] = groupByJob(LEDGER);
    expect(g!.latestAt).toBe("2026-07-15T11:30:00Z");
  });

  it("separates multiple jobs, newest first", () => {
    const older = entry({
      job_id: "22222222-2222-2222-2222-222222222222",
      created_at: "2026-07-14T09:00:00Z",
    });
    const groups = groupByJob([...LEDGER, older]);
    expect(groups).toHaveLength(2);
    expect(groups[0]!.jobId).toBe(JOB); // newer group first
  });
});

describe("toCsv", () => {
  it("emits a header and one row per leg with 6-dp amounts", () => {
    const csv = toCsv(LEDGER);
    const lines = csv.split("\n");
    expect(lines[0]).toBe("created_at,job_id,entry_group,account,direction,amount,reason");
    expect(lines).toHaveLength(LEDGER.length + 1);
    expect(lines[1]).toContain("10.000000");
    expect(lines[1]).toContain(JOB);
  });

  it("escapes fields containing commas or quotes", () => {
    const csv = toCsv([entry({ reason: 'a,b"c', amount: 1 })]);
    expect(csv.split("\n")[1]).toContain('"a,b""c"');
  });
});
