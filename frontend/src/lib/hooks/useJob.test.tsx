import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Job } from "@/lib/api/types";

const h = vi.hoisted(() => ({ connected: false, getJob: vi.fn() }));

vi.mock("@/lib/realtime/RealtimeProvider", () => ({
  useRealtime: () => ({ connected: h.connected }),
}));
vi.mock("@/lib/api/browser", () => ({ api: { getJob: h.getJob } }));

import { useJob } from "./useJob";

function makeJob(overrides: Partial<Job>): Job {
  return { id: "j1", status: "queued", ...overrides } as unknown as Job;
}

/** Advance fake timers inside act() so react-query state updates settle cleanly. */
function advance(ms: number) {
  return act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("useJob — adaptive polling vs. SSE", () => {
  beforeEach(() => {
    h.connected = false;
    h.getJob.mockReset();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls a non-terminal job while the stream is disconnected", async () => {
    h.connected = false;
    h.getJob.mockResolvedValue(makeJob({ status: "running" }));
    renderHook(() => useJob("j1"), { wrapper });

    await advance(0);
    expect(h.getJob).toHaveBeenCalledTimes(1);

    await advance(3000);
    expect(h.getJob).toHaveBeenCalledTimes(2);
  });

  it("pauses polling while the SSE stream is connected", async () => {
    h.connected = true;
    h.getJob.mockResolvedValue(makeJob({ status: "running" }));
    renderHook(() => useJob("j1"), { wrapper });

    await advance(0);
    expect(h.getJob).toHaveBeenCalledTimes(1);

    await advance(20_000);
    expect(h.getJob).toHaveBeenCalledTimes(1);
  });
});
