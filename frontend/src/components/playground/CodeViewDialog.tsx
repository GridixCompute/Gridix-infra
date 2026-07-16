"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { env } from "@/lib/config/env";
import { isMockInference } from "@/lib/inference/mock";
import { renderSnippet, SNIPPET_LANGS, type SnippetLang } from "@/lib/inference/snippets";

/**
 * Shows the request the playground just built, as code you can paste (Sesi 5.3).
 *
 * The bridge from playground to API: whatever you tuned here, this is the call that does the
 * same thing from your own program. `body` is the actual request object the client sends —
 * not a re-typed copy — so what you read is what runs.
 *
 * Native <dialog> rather than a bespoke modal: it gets focus trapping, Escape, and the
 * top-layer stacking for free, and the app has no Modal component to reuse yet.
 */

type Props = {
  open: boolean;
  onClose: () => void;
  /** API path, e.g. "/v1/chat/completions". */
  path: string;
  /** The exact request body the client would POST. */
  body: unknown;
};

export function CodeViewDialog({ open, onClose, path, body }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [lang, setLang] = useState<SnippetLang>("curl");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(t);
  }, [copied]);

  const code = renderSnippet(lang, env.apiUrl, path, body);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => {
        // Click outside the panel closes: <dialog> reports the backdrop as itself.
        if (e.target === ref.current) onClose();
      }}
      aria-labelledby="codeview-title"
      className="w-[min(46rem,92vw)] rounded-[var(--radius-md)] border border-[var(--color-hairline)] bg-[var(--color-panel)] p-0 text-[var(--color-ink)] backdrop:bg-black/60"
    >
      <div className="space-y-4 p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2
              id="codeview-title"
              className="text-lg font-[var(--font-display)] font-bold text-[var(--color-ink)]"
            >
              Call this from your code
            </h2>
            <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
              The exact request this playground sends —{" "}
              <code className="text-xs font-[var(--font-mono)]">{path}</code>
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            ✕
          </Button>
        </div>

        {isMockInference && (
          <p className="rounded-[var(--radius-sm)] border border-[var(--color-warning)] bg-[#ffab3d14] px-3 py-2 text-xs text-[var(--color-ink-soft)]">
            <strong className="text-[var(--color-warning)]">Not runnable yet.</strong> This matches
            what the playground sends, but the endpoint doesn&apos;t exist — running it today
            returns 404.
          </p>
        )}

        <div role="tablist" aria-label="Language" className="flex gap-1">
          {SNIPPET_LANGS.map((l) => (
            <button
              key={l.id}
              role="tab"
              aria-selected={lang === l.id}
              onClick={() => setLang(l.id)}
              className={[
                "rounded-[var(--radius-sm)] px-3 py-1 text-xs transition-colors",
                "focus-visible:ring-2 focus-visible:ring-[var(--color-signal)] focus-visible:outline-none",
                lang === l.id
                  ? "bg-[var(--color-signal)] font-medium text-[var(--color-void)]"
                  : "text-[var(--color-ink-soft)] hover:bg-[var(--color-panel-raised)]",
              ].join(" ")}
            >
              {l.label}
            </button>
          ))}
        </div>

        <pre className="max-h-[50vh] overflow-auto rounded-[var(--radius-sm)] border border-[var(--color-hairline)] bg-[var(--color-void)] p-3 text-xs leading-relaxed font-[var(--font-mono)] text-[var(--color-ink-soft)]">
          {code}
        </pre>

        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-[var(--color-ink-faint)]">
            Your session key is never printed — set <code>GRIDIX_API_KEY</code> yourself.
          </p>
          <Button
            size="sm"
            onClick={() => {
              void navigator.clipboard.writeText(code).then(() => setCopied(true));
            }}
          >
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      </div>
    </dialog>
  );
}
