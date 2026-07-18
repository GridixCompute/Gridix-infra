import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ChatPanel } from "./ChatPanel";
import { MOCK_MODELS } from "@/lib/inference/mock";
import type { ChatParams } from "@/lib/inference/types";

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

const CHAT_MODEL = MOCK_MODELS.find((m) => m.kind === "chat" && m.available)!;
const PARAMS: ChatParams = { temperature: 0.7, maxTokens: 512, topP: 1, seed: null };

describe("ChatPanel — balance gate", () => {
  it("blocks sending when the estimate exceeds the balance", () => {
    render(<ChatPanel model={CHAT_MODEL} params={PARAMS} availableBase={0n} />);

    expect(screen.getByRole("alert")).toHaveTextContent(/more than your balance/i);
    expect(screen.getByRole("link", { name: /top up/i })).toHaveAttribute("href", "/billing");
    expect(screen.getByLabelText("Prompt")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("allows sending when the balance covers the estimate", () => {
    // 1 USDC — comfortably above a 512-token turn on the mock rate card.
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
    const offline = MOCK_MODELS.find((m) => m.kind === "chat" && !m.available)!;
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
