import type { BrowserContext, Page, Route } from "@playwright/test";

/**
 * Shared E2E helpers (Sesi 12). Auth is simulated by setting the same cookies
 * the login route would set; all backend traffic is mocked at the network layer
 * so tests are deterministic and need no live backend or chain.
 */

const ORIGIN = "http://localhost:3100";

/** Seed the session cookies a logged-in developer would have. */
export async function loginAs(
  context: BrowserContext,
  role: "developer" | "provider" = "developer",
): Promise<void> {
  await context.addCookies([
    { name: "gridix_session", value: "grdx_e2e_key", url: ORIGIN, httpOnly: true },
    { name: "gridix_role", value: role, url: ORIGIN },
    { name: "gridix_dev", value: role === "provider" ? "Aurora GPU Farm" : "Acme AI", url: ORIGIN },
  ]);
}

export type Job = Record<string, unknown>;

/** A JobResponse-shaped fixture; override any field. */
export function makeJob(overrides: Job = {}): Job {
  const now = "2026-07-15T10:00:00Z";
  return {
    id: "11111111-1111-1111-1111-111111111111",
    developer_id: "22222222-2222-2222-2222-222222222222",
    kind: "standard",
    status: "completed",
    image_ref: "ghcr.io/acme/trainer:latest",
    input_ref: null,
    result_ref: "blob://result",
    resource_spec: { cpu_cores: 1, memory_mb: 512, gpu: false, gpu_vram_mb: 0 },
    allow_egress: false,
    timeout_seconds: 300,
    is_high_value: false,
    redundancy: 1,
    exposed_port: null,
    data_tier: "public",
    assigned_provider_id: "33333333-3333-3333-3333-333333333333",
    attempt_count: 1,
    lease_expires_at: null,
    escrow_amount: 5.0,
    cost_final: 5.0,
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

export function makeAudit(job: Job): Record<string, unknown> {
  return {
    job,
    attempts: [
      {
        provider_id: "33333333-3333-3333-3333-333333333333",
        attempt_number: 1,
        outcome: "completed",
        result_ref: "blob://result",
        started_at: "2026-07-15T10:00:05Z",
        finished_at: "2026-07-15T10:00:47Z",
      },
    ],
    ledger: [
      {
        account: "developer",
        account_ref: "22222222-2222-2222-2222-222222222222",
        direction: "debit",
        amount: 5.0,
        reason: "escrow_hold",
        created_at: "2026-07-15T10:00:00Z",
      },
    ],
  };
}

function fulfill(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

export type ApiMocks = {
  jobs?: Job[];
  job?: Job;
  audit?: Record<string, unknown>;
  summary?: Record<string, unknown>;
  ledger?: unknown[];
  /** Response for POST /jobs — a job (201) or an error like { status, detail }. */
  submit?: Job | { status: number; detail: string };
  /** Force an error on GET /jobs — e.g. { status: 500 } or { status: 401 }. */
  jobsError?: { status: number; detail?: string };
  result?: string;
};

/**
 * Install network mocks for every backend call the app makes. The SSE stream is
 * always stubbed so the realtime provider falls back to polling the mocked list.
 */
export async function mockApi(page: Page, mocks: ApiMocks = {}): Promise<void> {
  // Realtime stream: return an immediately-closing stream → app polls instead.
  await page.route("**/api/gw/events", (route) =>
    route.fulfill({ status: 200, contentType: "text/event-stream", body: ":ok\n\n" }),
  );

  await page.route("**/api/gw/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/gw", "");
    const method = route.request().method();

    if (path === "/jobs" && method === "GET") {
      if (mocks.jobsError)
        return fulfill(
          route,
          { detail: mocks.jobsError.detail ?? "error" },
          mocks.jobsError.status,
        );
      return fulfill(route, mocks.jobs ?? []);
    }
    if (path === "/jobs" && method === "POST") {
      const s = mocks.submit;
      if (s && "status" in s && typeof s.status === "number") {
        return fulfill(route, { detail: (s as { detail: string }).detail }, s.status as number);
      }
      return fulfill(route, s ?? makeJob({ status: "queued" }), 201);
    }
    if (/^\/jobs\/[^/]+\/audit$/.test(path) && method === "GET") {
      return fulfill(route, mocks.audit ?? makeAudit(mocks.job ?? makeJob()));
    }
    if (/^\/jobs\/[^/]+\/result$/.test(path)) {
      return route.fulfill({
        status: 200,
        contentType: "application/octet-stream",
        headers: { "content-disposition": 'attachment; filename="result.bin"' },
        body: mocks.result ?? "RESULT_BYTES",
      });
    }
    if (/^\/jobs\/[^/]+$/.test(path) && method === "GET") {
      return fulfill(route, mocks.job ?? makeJob());
    }
    if (path === "/billing/summary") {
      return fulfill(
        route,
        mocks.summary ?? {
          total_spent: 0,
          provider_paid: 0,
          protocol_fees: 0,
          data_costs: 0,
          total_refunded: 0,
          total_held: 0,
          total_escrowed: 0,
          job_count: 0,
          balanced: true,
        },
      );
    }
    if (path === "/billing/ledger") {
      return fulfill(route, mocks.ledger ?? []);
    }
    return fulfill(route, null, 404);
  });
}
