"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { createChatCompletion, inferenceErrorMessage } from "@/lib/inference/client";
import { estimateChatCost } from "@/lib/inference/pricing";
import { toBaseUnits } from "@/lib/format/usdc";
import type { ChatCompletionRequest, ChatMessage, ModelInfo } from "@/lib/inference/contract";
import type { ChatParams } from "@/lib/inference/params";
import { CodeViewDialog } from "./CodeViewDialog";

/**
 * The conversation surface.
 *
 * Turns carry their own cost: the ESTIMATE before sending, replaced by the `cost_usdc` the
 * backend reports on the response. Never show one as the other — see pricing.ts.
 *
 * ⚠️ NOT STREAMED. The backend answers `stream=true` with 501, so a reply arrives whole. The
 * panel previously rendered a token-by-token typewriter fed by the mock alone; against the
 * real API it would have shown a caret that never moved and then the entire reply at once.
 * Cancel therefore discards the turn rather than keeping a partial one — there is no partial
 * one to keep, and nothing is billed for a request whose response was never read.
 */

type Turn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** USDC base units actually charged, once the response reports it. */
  costBase?: bigint;
  /** True while the request is in flight. */
  pending?: boolean;
};

type Props = {
  model: ModelInfo | undefined;
  params: ChatParams;
  /** Available balance in base units (6dp), or null when it can't be read. */
  availableBase: bigint | null;
};

let turnSeq = 0;
const nextId = () => `turn-${++turnSeq}`;

/**
 * The request the client sends. Shared with CodeViewDialog so the snippet shown is the call
 * actually made, not a re-typed lookalike that drifts the first time either changes.
 */
function buildRequest(
  model: ModelInfo,
  messages: ChatMessage[],
  params: ChatParams,
): ChatCompletionRequest {
  return {
    model: model.id,
    messages,
    // False, not a toggle: `stream=true` is a 501. `top_p` is absent because
    // ChatCompletionRequest has no such field — the panel used to send one.
    stream: false,
    temperature: params.temperature,
    max_tokens: params.maxTokens,
    seed: params.seed,
    data_tier: "public",
  };
}

export function ChatPanel({ model, params, availableBase }: Props) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showCode, setShowCode] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Follow the stream, but only from the bottom: yanking the view back while someone is
  // reading earlier output is worse than not following at all.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [turns]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const history: ChatMessage[] = turns.map((t) => ({ role: t.role, content: t.content }));
  const pending: ChatMessage[] = draft.trim()
    ? [...history, { role: "user", content: draft.trim() }]
    : history;
  const estimate = estimateChatCost(model, pending, params.maxTokens);

  const unaffordable =
    availableBase !== null && model !== undefined && estimate.base > availableBase;
  const blocked = !model?.available || unaffordable;

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text || !model || busy || blocked) return;

    const userTurn: Turn = { id: nextId(), role: "user", content: text };
    const replyTurn: Turn = { id: nextId(), role: "assistant", content: "", pending: true };
    setTurns((prev) => [...prev, userTurn, replyTurn]);
    setDraft("");
    setError(null);
    setBusy(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await createChatCompletion(
        buildRequest(model, [...history, { role: "user", content: text }], params),
        controller.signal,
      );
      const reply = res.choices[0]?.message.content ?? "";
      setTurns((prev) =>
        prev.map((t) =>
          t.id === replyTurn.id
            ? { ...t, content: reply, pending: false, costBase: toBaseUnits(res.cost_usdc) }
            : t,
        ),
      );
    } catch (e) {
      // A cancel is not a failure: drop the placeholder and say nothing.
      if ((e as Error)?.name !== "AbortError") setError(inferenceErrorMessage(e));
      setTurns((prev) => prev.filter((t) => t.id !== replyTurn.id));
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }, [draft, model, busy, blocked, history, params]);

  const stop = () => abortRef.current?.abort();

  const regenerate = () => {
    // Drop the last reply and resend the prompt that produced it.
    const lastUser = [...turns].reverse().find((t) => t.role === "user");
    if (!lastUser || busy) return;
    setTurns((prev) => {
      const idx = prev.findIndex((t) => t.id === lastUser.id);
      return prev.slice(0, idx);
    });
    setDraft(lastUser.content);
  };

  const spentBase = turns.reduce((sum, t) => sum + (t.costBase ?? 0n), 0n);

  return (
    <div className="flex h-full flex-col gap-4">
      <div
        ref={scrollRef}
        className="min-h-[22rem] flex-1 space-y-4 overflow-y-auto rounded-[var(--radius-md)] border border-[var(--color-hairline)] bg-[var(--color-panel)] p-4"
      >
        {turns.length === 0 ? (
          <p className="py-16 text-center text-sm text-[var(--color-ink-faint)]">
            Ask the model something to start.
          </p>
        ) : (
          turns.map((turn) => (
            <div
              key={turn.id}
              className={turn.role === "user" ? "flex justify-end" : "flex justify-start"}
            >
              <div
                className={[
                  "max-w-[85%] rounded-[var(--radius-md)] px-3.5 py-2.5 text-sm whitespace-pre-wrap",
                  turn.role === "user"
                    ? "bg-[var(--color-signal-glow)] text-[var(--color-ink)]"
                    : "bg-[var(--color-panel-raised)] text-[var(--color-ink-soft)]",
                ].join(" ")}
              >
                {turn.content}
                {/* A whole reply arrives at once, so this is a wait indicator, not a
                    typewriter caret pretending tokens are trickling in. */}
                {turn.pending && (
                  <span
                    role="status"
                    aria-label="Generating"
                    className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--color-hairline-strong)] border-t-[var(--color-signal)]"
                  />
                )}
                {turn.costBase !== undefined && (
                  <span className="mt-1.5 flex items-center gap-2 text-xs text-[var(--color-ink-faint)]">
                    <USDCAmount base={turn.costBase} minFractionDigits={6} />
                  </span>
                )}
              </div>
            </div>
          ))
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-[var(--color-danger)]">
          {error}
        </p>
      )}

      {/* 4.5 — refuse before the request, not after the node does. */}
      {unaffordable && (
        <p role="alert" className="text-sm text-[var(--color-warning)]">
          This turn costs about <USDCAmount base={estimate.base} minFractionDigits={6} /> — more
          than your balance.{" "}
          <a href="/billing" className="text-[var(--color-signal-bright)] underline">
            Top up
          </a>{" "}
          to continue.
        </p>
      )}
      {model && !model.available && (
        <p role="alert" className="text-sm text-[var(--color-warning)]">
          No provider is serving {model.id} right now. Pick another model.
        </p>
      )}

      <div className="space-y-2">
        <textarea
          aria-label="Prompt"
          rows={3}
          value={draft}
          disabled={blocked}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void send();
          }}
          placeholder={blocked ? "Sending is blocked — see above." : "Send a message…  (⌘↵)"}
          className="w-full resize-y rounded-[var(--radius-md)] border border-[var(--color-hairline)] bg-[var(--color-panel)] px-3.5 py-2.5 text-sm text-[var(--color-ink)] placeholder:text-[var(--color-ink-disabled)] focus-visible:border-[var(--color-signal)] focus-visible:ring-2 focus-visible:ring-[var(--color-signal-glow)] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60"
        />

        <div className="flex flex-wrap items-center gap-3">
          {/* "Cancel", not "Stop": there is no partial reply to stop — the request is
              abandoned and the turn discarded. */}
          {busy ? (
            <Button variant="secondary" onClick={stop}>
              Cancel
            </Button>
          ) : (
            <Button onClick={() => void send()} disabled={!draft.trim() || blocked}>
              Send
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={regenerate}
            disabled={busy || turns.length === 0}
          >
            Regenerate
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setTurns([]);
              setError(null);
            }}
            disabled={busy || turns.length === 0}
          >
            Clear
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowCode(true)}
            disabled={!model || pending.length === 0}
          >
            View code
          </Button>

          <span className="ml-auto flex items-center gap-3 text-xs text-[var(--color-ink-faint)]">
            <span title="Worst case: prompt + the full max_tokens reply">
              est. <USDCAmount base={estimate.base} minFractionDigits={6} />
            </span>
            {spentBase > 0n && (
              <span>
                spent <USDCAmount base={spentBase} minFractionDigits={6} />
              </span>
            )}
            {availableBase !== null && (
              <span>
                balance <USDCAmount base={availableBase} tone="signal" />
              </span>
            )}
          </span>
        </div>
      </div>

      {model && (
        <CodeViewDialog
          open={showCode}
          onClose={() => setShowCode(false)}
          path="/v1/chat/completions"
          body={buildRequest(model, pending, params)}
        />
      )}
    </div>
  );
}
