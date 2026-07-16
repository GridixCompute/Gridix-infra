"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { MAX_BLOB_BYTES } from "@/lib/api/browser";
import { isApiError } from "@/lib/api/errors";
import { formatBytes } from "@/lib/format/bytes";
import { useUploadBlob } from "@/lib/hooks/useUploadBlob";

/** A staged input blob: stored backend-side, waiting to be attached to a job. */
export type StagedInput = { ref: string; name: string; size: number };

type Props = {
  value: StagedInput | null;
  onChange: (value: StagedInput | null) => void;
  /** Lifted so the form can block submit while bytes are still in flight. */
  onUploadingChange?: (uploading: boolean) => void;
};

/**
 * Input-data picker for a job (`POST /blobs` → `input_ref`). The file uploads on
 * selection rather than at submit, so a large transfer can't silently stall the
 * job POST, and a failed upload is retryable without re-entering the form.
 */
export function JobInputField({ value, onChange, onUploadingChange }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const upload = useUploadBlob();
  // Oversize is rejected before any request, so it can't live in upload.error.
  const [sizeError, setSizeError] = useState<string | null>(null);

  async function onPick(file: File) {
    onChange(null);
    upload.reset();
    if (file.size > MAX_BLOB_BYTES) {
      setSizeError(
        `That file is ${formatBytes(file.size)} — the limit is ${formatBytes(MAX_BLOB_BYTES)}.`,
      );
      return;
    }
    setSizeError(null);
    try {
      const blob = await upload.mutateAsync(file);
      onChange({ ref: blob.ref, name: file.name, size: blob.size });
    } catch {
      /* surfaced through upload.error */
    }
  }

  function clear() {
    onChange(null);
    upload.reset();
    setSizeError(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  const uploadError = upload.error
    ? isApiError(upload.error)
      ? upload.error.message
      : "Upload failed."
    : null;
  const error = sizeError ?? uploadError;

  return (
    <div className="space-y-3">
      <input
        ref={fileRef}
        type="file"
        className="sr-only"
        aria-label="Job input file"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void onPick(file);
        }}
      />

      {value ? (
        <div className="flex items-center justify-between gap-3 rounded-[var(--radius-sm)] border border-[var(--color-hairline-strong)] bg-[var(--color-abyss)] p-3">
          <div className="min-w-0">
            <p className="truncate text-sm text-[var(--color-ink)]">{value.name}</p>
            <p className="truncate font-[var(--font-mono)] text-xs text-[var(--color-ink-faint)]">
              {formatBytes(value.size)} · {value.ref}
            </p>
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={clear}>
            Remove
          </Button>
        </div>
      ) : (
        <Button
          type="button"
          variant="secondary"
          size="sm"
          loading={upload.isPending}
          onClick={() => fileRef.current?.click()}
        >
          {upload.isPending ? "Uploading…" : "Choose a file"}
        </Button>
      )}

      {error ? (
        <p className="text-xs text-[var(--color-danger)]">{error}</p>
      ) : (
        <p className="text-xs text-[var(--color-ink-faint)]">
          Mounted read-only in the container. Up to {formatBytes(MAX_BLOB_BYTES)}.
        </p>
      )}
    </div>
  );
}
