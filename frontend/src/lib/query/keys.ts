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
} as const;
