import { describe, it, expect } from "vitest";
import { isTerminal, JOB_STATUSES, TERMINAL_STATUSES } from "./types";

describe("job status helpers", () => {
  it("lists all six backend statuses in lifecycle order", () => {
    expect(JOB_STATUSES).toEqual([
      "queued",
      "assigned",
      "running",
      "completed",
      "failed",
      "timeout",
    ]);
  });

  it("treats completed/failed/timeout as terminal, others as active", () => {
    expect(isTerminal("completed")).toBe(true);
    expect(isTerminal("failed")).toBe(true);
    expect(isTerminal("timeout")).toBe(true);
    expect(isTerminal("queued")).toBe(false);
    expect(isTerminal("assigned")).toBe(false);
    expect(isTerminal("running")).toBe(false);
    expect(TERMINAL_STATUSES.size).toBe(3);
  });
});
