import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RealtimeProvider, useRealtime } from "./RealtimeProvider";
import { queryKeys } from "@/lib/query/keys";
import type { Job } from "@/lib/api/types";

/** A controllable EventSource stand-in — jsdom has none. Tests drive events by
 *  grabbing the constructed instance and calling `emit`. */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  closed = false;
  private listeners: Record<string, ((e: Event) => void)[]> = {};

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, cb: (e: Event) => void) {
    (this.listeners[type] ??= []).push(cb);
  }
  close() {
    this.closed = true;
  }
  emit(type: string, event: Event) {
    for (const cb of this.listeners[type] ?? []) cb(event);
  }
}

function makeJob(overrides: Partial<Job>): Job {
  return { id: "a", status: "queued", ...overrides } as unknown as Job;
}

function Status() {
  const { connected } = useRealtime();
  return <span>{connected ? "on" : "off"}</span>;
}

function renderProvider() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(queryKeys.jobs.list({}), [makeJob({ id: "a", status: "queued" })]);
  qc.setQueryData(queryKeys.jobs.detail("a"), makeJob({ id: "a", status: "queued" }));
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  const view = render(
    <QueryClientProvider client={qc}>
      <RealtimeProvider>
        <Status />
      </RealtimeProvider>
    </QueryClientProvider>,
  );
  const es = FakeEventSource.instances.at(-1)!;
  return { qc, invalidate, es, ...view };
}

describe("<RealtimeProvider>", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("opens one EventSource to the authenticated proxy", () => {
    const { es } = renderProvider();
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(es.url).toBe("/api/gw/events");
    expect(screen.getByText("off")).toBeInTheDocument();
  });

  it("marks connected and closes the gap on open", () => {
    const { es, invalidate } = renderProvider();
    act(() => es.emit("open", new Event("open")));
    expect(screen.getByText("on")).toBeInTheDocument();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.jobs.all });
  });

  it("patches the cached list and detail on a job event", () => {
    const { es, qc } = renderProvider();
    act(() =>
      es.emit(
        "job",
        new MessageEvent("job", {
          data: JSON.stringify(makeJob({ id: "a", status: "completed" })),
        }),
      ),
    );
    const list = qc.getQueryData<Job[]>(queryKeys.jobs.list({}))!;
    expect(list[0]!.status).toBe("completed");
    expect(qc.getQueryData<Job>(queryKeys.jobs.detail("a"))!.status).toBe("completed");
  });

  it("prepends a job not already in the list", () => {
    const { es, qc } = renderProvider();
    act(() =>
      es.emit(
        "job",
        new MessageEvent("job", { data: JSON.stringify(makeJob({ id: "b", status: "queued" })) }),
      ),
    );
    const list = qc.getQueryData<Job[]>(queryKeys.jobs.list({}))!;
    expect(list.map((j) => j.id)).toEqual(["b", "a"]);
  });

  it("ignores a malformed event payload without throwing", () => {
    const { es, qc } = renderProvider();
    act(() => es.emit("job", new MessageEvent("job", { data: "{not json" })));
    expect(qc.getQueryData<Job[]>(queryKeys.jobs.list({}))).toHaveLength(1);
  });

  it("reflects a dropped stream so polling can resume", () => {
    const { es } = renderProvider();
    act(() => es.emit("open", new Event("open")));
    expect(screen.getByText("on")).toBeInTheDocument();
    act(() => es.emit("error", new Event("error")));
    expect(screen.getByText("off")).toBeInTheDocument();
  });

  it("closes the stream on unmount", () => {
    const { es, unmount } = renderProvider();
    unmount();
    expect(es.closed).toBe(true);
  });
});
