"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { USDCAmount } from "@/components/domain/USDCAmount";
import { inferenceErrorMessage, streamChat } from "@/lib/inference/client";
import { estimateChatCost, microToBase } from "@/lib/inference/pricing";
import type { ChatMessage, ChatParams, InferenceModel } from "@/lib/inference/types";

/**
 * The conversation surface (Sesi 4.3).
 *
 * Turns carry their own cost: the ESTIMATE while generating, replaced by the charge the
 * backend reports when the stream closes. Never show one as the other — see pricing.ts.
 */

type Turn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** Micro-USDC actually charged, once the stream reports it. */
  costMicro?: number;
  /** True while tokens are still arriving. */
  streaming?: boolean;
  /** Set when the user hit stop — the partial reply is kept and still billable. */
  stopped?: boolean;
};

type Props = {
  model: InferenceModel | undefined;
  params: ChatParams;
  /** Available balance in base units (6dp), or null when it can't be read. */
  availableBase: bigint | null;
};

let turnSeq = 0;
const nextId = () => `turn-${++turnSeq}`;

export function ChatPanel({ model, params, availableBase }: Props) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
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
    availableBase !== null && model !== undefined && microToBase(estimate.micro) > availableBase;
  const blocked = !model?.available || unaffordable;

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text || !model || busy || blocked) return;

    const userTurn: Turn = { id: nextId(), role: "user", content: text };
    const replyTurn: Turn = { id: nextId(), role: "assistant", content: "", streaming: true };
    setTurns((prev) => [...prev, userTurn, replyTurn]);
    setDraft("");
    setError(null);
    setBusy(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const stream = streamChat(
        {
          model: model.id,
          messages: [...history, { role: "user", content: text }],
          stream: true,
          temperature: params.temperature,
          max_tokens: params.maxTokens,
          top_p: params.topP,
          seed: params.seed,
        },
        controller.signal,
      );

      for await (const ev of stream) {
        if (ev.type === "delta") {
          setTurns((prev) =>
            prev.map((t) =>
              t.id === replyTurn.id ? { ...t, content: t.content + ev.content } : t,
            ),
          );
        } else {
          setTurns((prev) =>
            prev.map((t) =>
              t.id === replyTurn.id
                ? {
                    ...t,
                    streaming: false,
                    stopped: controller.signal.aborted,
                    costMicro: ev.usage?.cost_micro_usdc,
                  }
                : t,
            ),
          );
        }
      }
    } catch (e) {
      setError(inferenceErrorMessage(e));
      // Drop the empty reply rather than leave a blank bubble behind.
      setTurns((prev) => prev.filter((t) => t.id !== replyTurn.id || t.content !== ""));
      setTurns((prev) => prev.map((t) => (t.id === replyTurn.id ? { ...t, streaming: false } : t)));
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

  const spentMicro = turns.reduce((sum, t) => sum + (t.costMicro ?? 0), 0);

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
                {turn.streaming && (
                  <span
                    aria-label="generating"
                    className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 animate-pulse bg-[var(--color-signal)]"
                  />
                )}
                {(turn.costMicro !== undefined || turn.stopped) && (
                  <span className="mt-1.5 flex items-center gap-2 text-xs text-[var(--color-ink-faint)]">
                    {turn.costMicro !== undefined && (
                      <USDCAmount base={microToBase(turn.costMicro)} minFractionDigits={6} />
                    )}
                    {turn.stopped && <span>· stopped</span>}
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
          This turn costs about{" "}
          <USDCAmount base={microToBase(estimate.micro)} minFractionDigits={6} /> — more than your
          balance.{" "}
          <a href="/billing" className="text-[var(--color-signal-bright)] underline">
            Top up
          </a>{" "}
          to continue.
        </p>
      )}
      {model && !model.available && (
        <p role="alert" className="text-sm text-[var(--color-warning)]">
          No provider is serving {model.name} right now. Pick another model.
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
          {busy ? (
            <Button variant="secondary" onClick={stop}>
              Stop
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

          <span className="ml-auto flex items-center gap-3 text-xs text-[var(--color-ink-faint)]">
            <span title="Worst case: prompt + the full max_tokens reply">
              est. <USDCAmount base={microToBase(estimate.micro)} minFractionDigits={6} />
            </span>
            {spentMicro > 0 && (
              <span>
                spent <USDCAmount base={microToBase(spentMicro)} minFractionDigits={6} />
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
    </div>
  );
}
