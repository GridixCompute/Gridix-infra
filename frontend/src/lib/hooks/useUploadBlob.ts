"use client";

import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api/browser";
import type { BlobRef } from "@/lib/api/types";

/**
 * Stage a job's input blob. The upload runs when the file is chosen, not at
 * submit, so the job POST carries a ref the backend has already stored — a
 * failed upload can be retried without losing the rest of the form.
 */
export function useUploadBlob() {
  return useMutation<BlobRef, Error, File>({
    mutationFn: (file) => api.uploadBlob(file),
  });
}
