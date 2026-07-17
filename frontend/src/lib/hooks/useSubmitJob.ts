"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/browser";
import { queryKeys } from "@/lib/query/keys";
import type { Job, SubmitJobRequest } from "@/lib/api/types";

/**
 * Submit a job (Sesi 3.2) with an optimistic insert + clean rollback (Sesi 3.3).
 * On failure the temporary row is removed — no ghost jobs left behind.
 */
export function useSubmitJob() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (body: SubmitJobRequest) => api.submitJob(body),

    onMutate: async (body): Promise<{ tempId: string }> => {
      await qc.cancelQueries({ queryKey: queryKeys.jobs.all });
      const tempId = `optimistic-${crypto.randomUUID()}`;
      const optimistic = makeOptimisticJob(tempId, body);

      // Prepend to every cached jobs list.
      qc.setQueriesData<Job[]>({ queryKey: ["jobs", "list"] }, (old) =>
        old ? [optimistic, ...old] : [optimistic],
      );
      return { tempId };
    },

    onError: (_err, _body, ctx) => {
      if (!ctx) return;
      qc.setQueriesData<Job[]>({ queryKey: ["jobs", "list"] }, (old) =>
        old?.filter((j) => j.id !== ctx.tempId),
      );
    },

    onSuccess: (real, _body, ctx) => {
      // Swap the optimistic row for the real one.
      qc.setQueriesData<Job[]>({ queryKey: ["jobs", "list"] }, (old) =>
        old?.map((j) => (j.id === ctx?.tempId ? real : j)),
      );
    },

    onSettled: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.jobs.all });
    },
  });
}

function makeOptimisticJob(id: string, body: SubmitJobRequest): Job {
  const now = new Date().toISOString();
  return {
    id,
    developer_id: "",
    kind: "standard",
    status: "queued",
    image_ref: body.image_ref,
    input_ref: body.input_ref ?? null,
    result_ref: null,
    resource_spec: (body.resource_spec ?? {}) as Job["resource_spec"],
    allow_egress: body.allow_egress ?? false,
    timeout_seconds: body.timeout_seconds ?? 300,
    is_high_value: body.is_high_value ?? false,
    redundancy: 1,
    exposed_port: null,
    // Must mirror what the form actually sends; "standard" is not a backend tier,
    // so the optimistic row flashed a value no job can ever have.
    data_tier: body.data_tier ?? "public",
    assigned_provider_id: null,
    attempt_count: 0,
    lease_expires_at: null,
    escrow_amount: null,
    cost_final: null,
    created_at: now,
    updated_at: now,
  };
}
