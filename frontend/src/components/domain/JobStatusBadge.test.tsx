import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { JobStatusBadge } from "./JobStatusBadge";
import { JOB_STATUSES } from "@/lib/api/types";

describe("<JobStatusBadge>", () => {
  it("renders a human label for every backend status", () => {
    const labels: Record<string, string> = {
      queued: "Queued",
      assigned: "Assigned",
      running: "Running",
      completed: "Completed",
      failed: "Failed",
      timeout: "Timed out",
    };
    for (const status of JOB_STATUSES) {
      const { unmount } = render(<JobStatusBadge status={status} />);
      expect(screen.getByText(labels[status]!)).toBeInTheDocument();
      unmount();
    }
  });
});
