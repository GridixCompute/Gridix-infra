/** Structured query-key factory (Sesi 3.1). One source of truth for cache keys. */
export type JobFilters = {
  status?: string;
  limit?: number;
  offset?: number;
};

export const queryKeys = {
  jobs: {
    all: ["jobs"] as const,
    list: (filters: JobFilters = {}) => ["jobs", "list", filters] as const,
    detail: (id: string) => ["jobs", "detail", id] as const,
    audit: (id: string) => ["jobs", "audit", id] as const,
  },
  session: {
    current: ["session"] as const,
  },
  billing: {
    summary: ["billing", "summary"] as const,
    ledger: (limit = 200) => ["billing", "ledger", limit] as const,
  },
  provider: {
    me: ["provider", "me"] as const,
    benchmark: ["provider", "benchmark"] as const,
    trust: ["provider", "trust"] as const,
    bandwidth: ["provider", "bandwidth"] as const,
    jobs: (limit = 50) => ["provider", "jobs", limit] as const,
    reputation: (limit = 50) => ["provider", "reputation", limit] as const,
    disputes: ["provider", "disputes"] as const,
  },
} as const;
