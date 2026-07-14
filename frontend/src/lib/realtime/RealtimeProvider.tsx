"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Job } from "@/lib/api/types";
import { queryKeys } from "@/lib/query/keys";

/**
 * Real-time job updates over SSE. Opens one EventSource to the authenticated
 * proxy (/api/gw/events); every "job" event patches the query cache directly
 * (no refetch). While connected, polling pauses (see useJobs/useJob); if the
 * stream drops, EventSource reconnects and polling resumes as the fallback.
 * On (re)connect we invalidate the job lists to close any gap missed while down.
 */
const RealtimeContext = createContext<{ connected: boolean }>({ connected: false });

export function useRealtime() {
  return useContext(RealtimeContext);
}

export function RealtimeProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    // EventSource can't set headers; the httpOnly session cookie authenticates
    // the same-origin request, which the proxy turns into a Bearer call.
    const es = new EventSource("/api/gw/events");
    esRef.current = es;

    es.addEventListener("open", () => {
      setConnected(true);
      // Close any gap between the initial fetch and the stream baseline.
      void qc.invalidateQueries({ queryKey: queryKeys.jobs.all });
    });

    es.addEventListener("job", (e) => {
      let job: Job;
      try {
        job = JSON.parse((e as MessageEvent).data) as Job;
      } catch {
        return;
      }
      // Patch every cached jobs list.
      qc.setQueriesData<Job[]>({ queryKey: ["jobs", "list"] }, (old) => {
        if (!old) return old;
        const idx = old.findIndex((j) => j.id === job.id);
        if (idx === -1) return [job, ...old];
        const next = old.slice();
        next[idx] = job;
        return next;
      });
      // Patch the job detail cache.
      qc.setQueryData(queryKeys.jobs.detail(job.id), job);
    });

    es.addEventListener("error", () => {
      // EventSource auto-reconnects; reflect the drop so polling resumes.
      setConnected(false);
    });

    return () => {
      es.close();
      esRef.current = null;
      setConnected(false);
    };
  }, [qc]);

  return <RealtimeContext.Provider value={{ connected }}>{children}</RealtimeContext.Provider>;
}
