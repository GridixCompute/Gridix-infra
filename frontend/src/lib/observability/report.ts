/**
 * Client observability (Sesi 14.4). Provider-agnostic: errors and funnel events
 * are scrubbed of anything sensitive, then handed to a pluggable sink. Point the
 * sink at Sentry (or any backend) by calling `initObservability` once at boot;
 * until then it logs in dev and is a no-op in production. Crucially, an API key
 * or wallet address can NEVER leave the browser through this path — everything
 * is redacted first.
 */

export type ObservabilityEvent =
  | { type: "error"; message: string; stack?: string; context?: Record<string, unknown> }
  | { type: "event"; name: string; props?: Record<string, unknown> };

type Sink = (event: ObservabilityEvent) => void;

let sink: Sink | null = null;

/** Install the sink (e.g. a Sentry adapter). Call once at app boot. */
export function initObservability(fn: Sink): void {
  sink = fn;
}

const REDACTIONS: Array<[RegExp, string]> = [
  // GRIDIX API keys.
  [/grdx_[A-Za-z0-9_-]+/g, "grdx_[redacted]"],
  // Bearer tokens.
  [/Bearer\s+[A-Za-z0-9._-]+/gi, "Bearer [redacted]"],
  // Wallet addresses / tx hashes (20- or 32-byte hex).
  [/0x[a-fA-F0-9]{40,}/g, "0x[redacted]"],
  // Session cookie if it ever appears in a string.
  [/gridix_session=[^;\s]+/g, "gridix_session=[redacted]"],
];

/** Redact secrets and PII from a string (API keys, bearer tokens, addresses). */
export function scrubPII(input: string): string {
  return REDACTIONS.reduce((acc, [re, to]) => acc.replace(re, to), input);
}

function scrubValue(v: unknown): unknown {
  if (typeof v === "string") return scrubPII(v);
  if (Array.isArray(v)) return v.map(scrubValue);
  if (v && typeof v === "object") {
    return Object.fromEntries(Object.entries(v).map(([k, val]) => [k, scrubValue(val)]));
  }
  return v;
}

function emit(event: ObservabilityEvent): void {
  if (sink) {
    sink(event);
    return;
  }
  if (process.env.NODE_ENV !== "production") {
    console.warn("[observability]", event);
  }
  // Production without a configured sink: drop silently.
}

/** Report an error, scrubbing its message, stack, and any context first. */
export function reportError(error: unknown, context?: Record<string, unknown>): void {
  const err = error instanceof Error ? error : new Error(String(error));
  emit({
    type: "error",
    message: scrubPII(err.message),
    stack: err.stack ? scrubPII(err.stack) : undefined,
    context: context ? (scrubValue(context) as Record<string, unknown>) : undefined,
  });
}

/**
 * Record a funnel event (Sesi 14.4): register → deposit → first job. Props are
 * scrubbed; never pass raw keys or addresses.
 */
export function track(name: string, props?: Record<string, unknown>): void {
  emit({
    type: "event",
    name,
    props: props ? (scrubValue(props) as Record<string, unknown>) : undefined,
  });
}
