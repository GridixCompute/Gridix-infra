import type { JobStatus } from "@/lib/api/types";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/utils/cn";

/**
 * The single, app-wide rendering of a job status. Colors are meaningful, not
 * arbitrary (Session 2.4): green = live/done, red = failed, amber = timeout,
 * blue = dispatched, grey = waiting. Backend defines exactly 6 statuses.
 */
const CONFIG: Record<
  JobStatus,
  { label: string; tone: Parameters<typeof Badge>[0]["tone"]; dot: string; live?: boolean }
> = {
  queued: { label: "Queued", tone: "neutral", dot: "var(--color-status-queued)" },
  assigned: { label: "Assigned", tone: "info", dot: "var(--color-status-assigned)" },
  running: { label: "Running", tone: "signal", dot: "var(--color-status-running)", live: true },
  completed: { label: "Completed", tone: "success", dot: "var(--color-status-completed)" },
  failed: { label: "Failed", tone: "danger", dot: "var(--color-status-failed)" },
  timeout: { label: "Timed out", tone: "warning", dot: "var(--color-status-timeout)" },
};

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const c = CONFIG[status];
  return (
    <Badge tone={c.tone}>
      <span
        className={cn("h-1.5 w-1.5 rounded-full", c.live && "animate-pulse-dot")}
        style={{ backgroundColor: c.dot }}
        aria-hidden="true"
      />
      {c.label}
    </Badge>
  );
}
