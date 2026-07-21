"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAccount } from "wagmi";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import { ConnectWallet } from "@/components/chain/ConnectWallet";
import {
  PublicApiError,
  fetchImageQuota,
  generatePublicImage,
  streamPublicChat,
  type ImageQuota,
} from "@/lib/public/client";

/**
 * The public playground. No account required to open it, and none to chat.
 *
 * The two halves are gated differently ON PURPOSE, and the UI has to make that legible
 * rather than surprising:
 *
 *   CHAT  — anonymous, unmetered, no wallet. Rate-limited per IP server-side, which a
 *           visitor should never notice unless they are scripting it.
 *   IMAGE — requires a connected wallet, five per day per wallet, prompt-screened.
 *
 * So a visitor who opens the image tab without a wallet gets an INVITATION, not an error and
 * not a hidden tab. Hiding it would leave them unable to discover the feature; erroring
 * would tell them something is broken when nothing is. Saying "connect your wallet, five a
 * day" tells them exactly what to do and what they get.
 */

type Turn = { id: string; role: "user" | "assistant"; content: string; streaming?: boolean };

let seq = 0;
const nextId = () => `t-${++seq}`;

export function FreePlayground() {
  const [mode, setMode] = useState<"chat" | "image">("chat");

  return (
    <div className="space-y-6">
      <div role="tablist" aria-label="Playground mode" className="flex gap-1">
        {(["chat", "image"] as const).map((m) => (
          <button
            key={m}
            role="tab"
            aria-selected={mode === m}
            onClick={() => setMode(m)}
            className={[
              "rounded-[var(--radius-sm)] px-3.5 py-1.5 text-sm capitalize transition-colors",
              "focus-visible:ring-2 focus-visible:ring-[var(--color-signal)] focus-visible:outline-none",
              mode === m
                ? "bg-[var(--color-signal)] font-medium text-[var(--color-void)]"
                : "text-[var(--color-ink-soft)] hover:bg-[var(--color-panel)]",
            ].join(" ")}
          >
            {m}
          </button>
        ))}
      </div>

      {mode === "chat" ? <FreeChat /> : <FreeImages />}
    </div>
  );
}

function FreeChat() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text || busy) return;

    const history = turns.map((t) => ({ role: t.role, content: t.content }));
    const user: Turn = { id: nextId(), role: "user", content: text };
    const reply: Turn = { id: nextId(), role: "assistant", content: "", streaming: true };
    setTurns((prev) => [...prev, user, reply]);
    setDraft("");
    setError(null);
    setBusy(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const events = streamPublicChat(
        [...history, { role: "user", content: text }],
        {},
        controller.signal,
      );
      for await (const event of events) {
        if (event.kind === "delta") {
          setTurns((prev) =>
            prev.map((t) => (t.id === reply.id ? { ...t, content: t.content + event.content } : t)),
          );
        } else if (event.kind === "error") {
          setError(event.message);
        }
      }
      setTurns((prev) => prev.map((t) => (t.id === reply.id ? { ...t, streaming: false } : t)));
    } catch (e) {
      if ((e as Error)?.name !== "AbortError") {
        setError(e instanceof PublicApiError ? e.message : "Something went wrong. Try again.");
      }
      // Keep a partial reply; drop an empty bubble.
      setTurns((prev) =>
        prev.flatMap((t) =>
          t.id === reply.id ? (t.content === "" ? [] : [{ ...t, streaming: false }]) : [t],
        ),
      );
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }, [draft, busy, turns]);

  return (
    <div className="space-y-4">
      <div
        role="log"
        aria-label="Conversation"
        aria-live="polite"
        className="min-h-[20rem] space-y-4 overflow-y-auto rounded-[var(--radius-md)] border border-[var(--color-hairline)] bg-[var(--color-panel)] p-4"
      >
        {turns.length === 0 ? (
          <p className="py-14 text-center text-sm text-[var(--color-ink-faint)]">
            Ask anything. Free, no account needed.
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
                    role="status"
                    aria-label="Generating"
                    className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 animate-pulse bg-[var(--color-signal)]"
                  />
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

      <div className="space-y-2">
        <textarea
          aria-label="Prompt"
          rows={3}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void send();
          }}
          placeholder="Send a message…  (⌘↵)"
          className="w-full resize-y rounded-[var(--radius-md)] border border-[var(--color-hairline)] bg-[var(--color-panel)] px-3.5 py-2.5 text-sm text-[var(--color-ink)] placeholder:text-[var(--color-ink-disabled)] focus-visible:border-[var(--color-signal)] focus-visible:ring-2 focus-visible:ring-[var(--color-signal-glow)] focus-visible:outline-none"
        />
        <div className="flex items-center gap-3">
          {busy ? (
            <Button variant="secondary" onClick={() => abortRef.current?.abort()}>
              Cancel
            </Button>
          ) : (
            <Button onClick={() => void send()} disabled={!draft.trim()}>
              Send
            </Button>
          )}
          <span className="text-xs text-[var(--color-ink-faint)]">Free · no account needed</span>
        </div>
      </div>
    </div>
  );
}

function FreeImages() {
  const { isConnected } = useAccount();
  const [quota, setQuota] = useState<ImageQuota | null>(null);
  const [prompt, setPrompt] = useState("");
  const [images, setImages] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // The quota is the signed-in wallet's, so it is only readable once there is a session.
  // A null answer means "not signed in", which is a state to invite out of, not an error.
  const refreshQuota = useCallback(async () => {
    try {
      setQuota(await fetchImageQuota());
    } catch {
      setQuota(null);
    }
  }, []);

  useEffect(() => {
    void refreshQuota();
  }, [refreshQuota, isConnected]);

  const generate = useCallback(async () => {
    const text = prompt.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    try {
      const generated = await generatePublicImage(text);
      setImages((prev) => [...generated.map((g) => g.url), ...prev]);
      await refreshQuota();
    } catch (e) {
      setError(e instanceof PublicApiError ? e.message : "Couldn't generate that image.");
      // A refusal or a spent allowance both change what the counter should say.
      await refreshQuota();
    } finally {
      setBusy(false);
    }
  }, [prompt, busy, refreshQuota]);

  // Not connected: invite, don't error and don't hide.
  if (!isConnected || quota === null) {
    return (
      <Card>
        <CardBody className="space-y-4 text-center">
          <h2 className="text-lg font-[var(--font-display)] font-bold text-[var(--color-ink)]">
            Connect a wallet to generate images
          </h2>
          <p className="text-sm text-[var(--color-ink-soft)]">
            Image generation is free — <strong>5 per day</strong>, resetting at 00:00 UTC. It needs
            a wallet so the daily allowance can be counted against something. Chat stays open with
            no account at all.
          </p>
          <div className="flex justify-center">
            <ConnectWallet />
          </div>
        </CardBody>
      </Card>
    );
  }

  const exhausted = quota.remaining <= 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="text-[var(--color-ink-soft)]">
          {/* The number, plainly, so nobody has to discover the limit by hitting it. */}
          <strong data-testid="image-quota">
            {quota.remaining} of {quota.limit}
          </strong>{" "}
          free images left today
        </span>
        <span className="text-xs text-[var(--color-ink-faint)]">Resets {quota.resets}</span>
      </div>

      <div className="flex min-h-[18rem] items-center justify-center rounded-[var(--radius-md)] border border-[var(--color-hairline)] bg-[var(--color-panel)] p-4">
        {busy ? (
          <div className="space-y-3 text-center">
            <div
              role="status"
              aria-label="Generating"
              className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-[var(--color-hairline-strong)] border-t-[var(--color-signal)]"
            />
            <p className="text-sm text-[var(--color-ink-faint)]">Generating…</p>
          </div>
        ) : images[0] ? (
          /* A node-supplied URL; next/image needs a configured remote host, which this
             has not got. */
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={images[0]}
            alt={prompt}
            className="mx-auto max-h-[24rem] w-auto rounded-[var(--radius-sm)]"
          />
        ) : (
          <p className="text-sm text-[var(--color-ink-faint)]">
            Describe an image to generate one.
          </p>
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-[var(--color-danger)]">
          {error}
        </p>
      )}

      <div className="space-y-2">
        <textarea
          aria-label="Image prompt"
          rows={3}
          value={prompt}
          disabled={exhausted}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={
            exhausted ? "You've used today's free images." : "A wireframe globe at dusk…"
          }
          className="w-full resize-y rounded-[var(--radius-md)] border border-[var(--color-hairline)] bg-[var(--color-panel)] px-3.5 py-2.5 text-sm text-[var(--color-ink)] placeholder:text-[var(--color-ink-disabled)] focus-visible:border-[var(--color-signal)] focus-visible:ring-2 focus-visible:ring-[var(--color-signal-glow)] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60"
        />
        <Button onClick={() => void generate()} disabled={!prompt.trim() || busy || exhausted}>
          Generate
        </Button>
      </div>
    </div>
  );
}
