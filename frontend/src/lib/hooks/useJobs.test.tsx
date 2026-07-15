import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Job } from "@/lib/api/types";

const h = vi.hoisted(() => ({ connected: false, listJobs: vi.fn() }));

vi.mock("@/lib/realtime/RealtimeProvider", () => ({
  useRealtime: () => ({ connected: h.connected }),
}));
vi.mock("@/lib/api/browser", () => ({ api: { listJobs: h.listJobs } }));

import { useJobs } from "./useJobs";

function makeJob(overrides: Partial<Job>): Job {
  return { id: "a", status: "queued", ...overrides } as unknown as Job;
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

describe("useJobs — adaptive polling vs. SSE", () => {
  beforeEach(() => {
    h.connected = false;
    h.listJobs.mockReset();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls while a job is active and the stream is disconnected", async () => {
    h.connected = false;
    h.listJobs.mockResolvedValue([makeJob({ status: "running" })]);
    renderHook(() => useJobs(), { wrapper });

    await advance(0);
    expect(h.listJobs).toHaveBeenCalledTimes(1);

    await advance(4000);
    expect(h.listJobs).toHaveBeenCalledTimes(2);
  });

  it("pauses polling entirely while the SSE stream is connected", async () => {
    h.connected = true;
    h.listJobs.mockResolvedValue([makeJob({ status: "running" })]);
    renderHook(() => useJobs(), { wrapper });

    await advance(0);
    expect(h.listJobs).toHaveBeenCalledTimes(1);

    await advance(20_000);
    expect(h.listJobs).toHaveBeenCalledTimes(1);
  });

  it("stops polling once every job is terminal", async () => {
    h.connected = false;
    h.listJobs.mockResolvedValue([makeJob({ status: "completed" })]);
    renderHook(() => useJobs(), { wrapper });

    await advance(0);
    expect(h.listJobs).toHaveBeenCalledTimes(1);

    await advance(20_000);
    expect(h.listJobs).toHaveBeenCalledTimes(1);
  });
});
