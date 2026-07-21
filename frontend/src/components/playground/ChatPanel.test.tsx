import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatPanel } from "./ChatPanel";
import { MOCK_MODELS } from "@/lib/inference/mock";
import type { ChatParams } from "@/lib/inference/params";

/**
 * The balance gate (Session 4.5).
 *
 * Covered here rather than in the browser because the gate needs a real balance, which comes
 * from the on-chain escrow plus the backend ledger — neither of which runs in the dev
 * environment. The browser pass therefore exercises the balance-unknown path only; these
 * pin the two paths that matter.
 *
 * Both directions are asserted deliberately: a "blocked" assertion on its own proves nothing
 * if the panel happens to be blocked for some unrelated reason (no model, empty draft). The
 * affordable case is what shows the block is caused by the balance.
 */

const CHAT_MODEL = MOCK_MODELS.find((m) => m.modality === "chat" && m.available)!;
const PARAMS: ChatParams = { temperature: 0.7, maxTokens: 512, seed: null };

describe("ChatPanel — balance gate", () => {
  it("blocks sending when the estimate exceeds the balance", () => {
    render(<ChatPanel model={CHAT_MODEL} params={PARAMS} availableBase={0n} />);

    expect(screen.getByRole("alert")).toHaveTextContent(/more than your balance/i);
    expect(screen.getByRole("link", { name: /top up/i })).toHaveAttribute("href", "/billing");
    expect(screen.getByLabelText("Prompt")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("allows sending when the balance covers the estimate", () => {
    // 1 USDC — comfortably above a 512-token turn at 0.08 USDC / 1M output tokens.
    render(<ChatPanel model={CHAT_MODEL} params={PARAMS} availableBase={1_000_000n} />);

    expect(screen.queryByText(/more than your balance/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Prompt")).toBeEnabled();
    // Send stays disabled only because the draft is empty — not because of the balance.
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("does not gate when the balance is unknown", () => {
    // What the dev environment actually hits: no backend, so no balance to compare against.
    // Refusing here would lock out a user whose balance we simply failed to read.
    render(<ChatPanel model={CHAT_MODEL} params={PARAMS} availableBase={null} />);

    expect(screen.queryByText(/more than your balance/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Prompt")).toBeEnabled();
  });

  it("blocks a model no provider is serving, and says so", () => {
    const offline = MOCK_MODELS.find((m) => m.modality === "chat" && !m.available)!;
    render(<ChatPanel model={offline} params={PARAMS} availableBase={1_000_000n} />);

    expect(screen.getByRole("alert")).toHaveTextContent(/no provider is serving/i);
    expect(screen.getByLabelText("Prompt")).toBeDisabled();
  });

  it("prices the worst case: raising max tokens raises the estimate", () => {
    const { rerender } = render(
      <ChatPanel model={CHAT_MODEL} params={{ ...PARAMS, maxTokens: 64 }} availableBase={null} />,
    );
    const cheap = screen.getByTitle(/worst case/i).textContent;

    rerender(
      <ChatPanel model={CHAT_MODEL} params={{ ...PARAMS, maxTokens: 4096 }} availableBase={null} />,
    );
    const dear = screen.getByTitle(/worst case/i).textContent;

    expect(cheap).not.toEqual(dear);
  });
});

// ── Streaming: the typewriter, and Cancel actually severing the connection ────────────────

const streamMock = vi.fn();
vi.mock("@/lib/inference/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/inference/client")>();
  return { ...actual, streamChatCompletion: (...args: unknown[]) => streamMock(...args) };
});

/** Hand control of a stream to the test: push events, end it, or leave it hanging. */
function controllableStream() {
  const queue: unknown[] = [];
  let notify: (() => void) | null = null;
  let ended = false;

  return {
    push(event: unknown) {
      queue.push(event);
      notify?.();
    },
    end() {
      ended = true;
      notify?.();
    },
    generator: async function* () {
      while (true) {
        while (queue.length) yield queue.shift();
        if (ended) return;
        await new Promise<void>((resolve) => {
          notify = resolve;
        });
      }
    },
  };
}

/** The conversation live-region. Scoped because CodeViewDialog renders the same text
 * inside the request JSON it displays. */
const log = () => screen.getByRole("log", { name: "Conversation" });

describe("ChatPanel — streaming", () => {
  beforeEach(() => streamMock.mockReset());

  async function send(model = CHAT_MODEL) {
    const user = userEvent.setup();
    render(<ChatPanel model={model} params={PARAMS} availableBase={1_000_000n} />);
    await user.type(screen.getByLabelText("Prompt"), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));
    return user;
  }

  it("renders tokens progressively, not in one dump at the end", async () => {
    // The whole point of streaming. A client that buffered and rendered once at the end
    // would satisfy a final-text assertion while being, precisely, not streaming.
    const stream = controllableStream();
    streamMock.mockImplementation(() => stream.generator());

    await send();

    stream.push({ kind: "delta", content: "Hel" });
    await within(log()).findByText(/Hel/);
    // Still mid-generation: the caret is up and nothing has finished.
    expect(screen.getByLabelText("Generating")).toBeInTheDocument();

    stream.push({ kind: "delta", content: "lo" });
    await within(log()).findByText(/Hello/);

    stream.end();
    await waitFor(() => expect(screen.queryByLabelText("Generating")).not.toBeInTheDocument());
  });

  it("shows the cost the final usage event reports", async () => {
    const stream = controllableStream();
    streamMock.mockImplementation(() => stream.generator());

    await send();
    stream.push({ kind: "delta", content: "hi" });
    stream.push({
      kind: "usage",
      usage: { prompt_tokens: 10, completion_tokens: 2, total_tokens: 12 },
      costUsdc: "0.000105",
      providerId: "p",
    });
    stream.end();

    // 0.000105 USDC, rendered by the app's single USDC formatter.
    await within(log()).findByText(/0\.000105/);
  });

  it("CANCEL ABORTS THE REQUEST — not merely the rendering", async () => {
    // The coordinator stops the node only when the connection closes. A Cancel that just
    // hid output would leave a GPU generating and settle a hold for tokens never shown.
    const stream = controllableStream();
    let captured: AbortSignal | undefined;
    streamMock.mockImplementation((_req: unknown, signal?: AbortSignal) => {
      captured = signal;
      return stream.generator();
    });

    const user = await send();
    stream.push({ kind: "delta", content: "partial" });
    await within(log()).findByText(/partial/);

    expect(captured).toBeDefined();
    expect(captured!.aborted).toBe(false);

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(captured!.aborted).toBe(true);
  });

  it("keeps the partial reply after a cancel, because it was billed", async () => {
    // The coordinator settles the hold for the tokens actually produced, so hiding them
    // would mean charging for output the developer was never shown.
    const stream = controllableStream();
    streamMock.mockImplementation(() => stream.generator());

    const user = await send();
    stream.push({ kind: "delta", content: "partial answer" });
    await within(log()).findByText(/partial answer/);

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    stream.end();

    await within(log()).findByText(/stopped/);
    expect(within(log()).getByText(/partial answer/)).toBeInTheDocument();
  });

  it("surfaces an in-band error event", async () => {
    // After bytes have flowed the backend reports failure as an event, not a status.
    const stream = controllableStream();
    streamMock.mockImplementation(() => stream.generator());

    await send();
    stream.push({ kind: "delta", content: "a" });
    stream.push({ kind: "error", message: "The node failed to complete the request." });
    stream.end();

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/node failed to complete/i),
    );
  });
});
