/**
 * Error taxonomy (Session 1.5). Every failure class maps to a distinct internal
 * shape and a message that tells the user WHAT went wrong and HOW to fix it.
 * FastAPI 422 validation detail is parsed into per-field errors.
 */

export type ApiErrorKind =
  | "unauthorized" // 401 — session invalid/expired
  | "forbidden" // 403 — e.g. insufficient balance gate
  | "not_found" // 404
  | "conflict" // 409 — idempotency / state clash
  | "validation" // 422 — per-field
  | "rate_limited" // 429
  | "server" // 5xx
  | "network" // fetch failed / offline / aborted
  | "unknown";

export type FieldError = { field: string; message: string };

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number;
  readonly fieldErrors: FieldError[];
  readonly retryable: boolean;

  constructor(init: {
    kind: ApiErrorKind;
    status: number;
    message: string;
    fieldErrors?: FieldError[];
    retryable?: boolean;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.kind = init.kind;
    this.status = init.status;
    this.fieldErrors = init.fieldErrors ?? [];
    this.retryable = init.retryable ?? false;
  }

  /** Look up the message for a specific form field (Session 1.5 / 7.5). */
  fieldError(field: string): string | undefined {
    return this.fieldErrors.find((f) => f.field === field)?.message;
  }
}

function kindForStatus(status: number): ApiErrorKind {
  switch (status) {
    case 401:
      return "unauthorized";
    case 403:
      return "forbidden";
    case 404:
      return "not_found";
    case 409:
      return "conflict";
    case 422:
      return "validation";
    case 429:
      return "rate_limited";
    default:
      return status >= 500 ? "server" : "unknown";
  }
}

const DEFAULT_MESSAGE: Record<ApiErrorKind, string> = {
  unauthorized: "Your session has expired. Sign in again to continue.",
  forbidden: "You don't have access to this — or your balance is too low for the action.",
  not_found: "We couldn't find what you were looking for.",
  conflict: "That action conflicts with the current state. Refresh and try again.",
  validation: "Some fields need attention.",
  rate_limited: "Too many requests. Wait a moment and try again.",
  server: "GRIDIX had a problem on our side. We're on it — try again shortly.",
  network: "Can't reach GRIDIX. Check your connection and try again.",
  unknown: "Something went wrong. Try again.",
};

type FastApiValidationDetail = {
  detail?: Array<{ loc?: (string | number)[]; msg?: string }> | string;
};

/** Parse a fetch Response into a typed ApiError. Never throws itself. */
export async function toApiError(res: Response): Promise<ApiError> {
  const kind = kindForStatus(res.status);
  let message = DEFAULT_MESSAGE[kind];
  let fieldErrors: FieldError[] = [];

  const body = await res.text().catch(() => "");
  if (body) {
    try {
      const parsed = JSON.parse(body) as FastApiValidationDetail;
      if (kind === "validation" && Array.isArray(parsed.detail)) {
        fieldErrors = parsed.detail.map((d) => ({
          // FastAPI loc is like ["body", "field", ...] — drop the "body" root.
          field: (d.loc ?? []).filter((p) => p !== "body").join("."),
          message: d.msg ?? "Invalid value.",
        }));
        if (fieldErrors.length > 0) message = fieldErrors[0]!.message;
      } else if (typeof parsed.detail === "string" && parsed.detail.trim()) {
        message = parsed.detail;
      }
    } catch {
      // Non-JSON body — keep the default message.
    }
  }

  return new ApiError({
    kind,
    status: res.status,
    message,
    fieldErrors,
    retryable: kind === "server" || kind === "rate_limited",
  });
}

/** Wrap a thrown fetch/abort/offline failure into a network ApiError. */
export function toNetworkError(cause: unknown): ApiError {
  const aborted = cause instanceof DOMException && cause.name === "AbortError";
  return new ApiError({
    kind: "network",
    status: 0,
    message: aborted ? "The request timed out. Try again." : DEFAULT_MESSAGE.network,
    retryable: !aborted,
  });
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}
