import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PlaygroundShell } from "./PlaygroundShell";

/**
 * Honest degradation when the balance can't be read.
 *
 * A null balance switches the spend guard off, and three unrelated causes produce one: no
 * wallet, no ledger, still loading. Before this, all three silently removed the balance line
 * and the page looked perfectly normal — with nothing stopping an unaffordable request.
 *
 * These pin that each cause says which it is, and — the half that actually proves the others
 * mean something — that a readable balance shows no warning at all.
 */

const h = vi.hoisted(() => ({
  address: undefined as string | undefined,
  escrow: undefined as bigint | undefined,
  summary: undefined as unknown,
}));

vi.mock("wagmi", () => ({ useAccount: () => ({ address: h.address }) }));
vi.mock("@/lib/chain/hooks", () => ({ useEscrowBalance: () => ({ data: h.escrow }) }));
vi.mock("@/lib/hooks/useBilling", () => ({ useBillingSummary: () => ({ data: h.summary }) }));

function renderShell() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PlaygroundShell />
    </QueryClientProvider>,
  );
}

describe("PlaygroundShell — the balance gap is explained, not hidden", () => {
  beforeEach(() => {
    h.address = undefined;
    h.escrow = undefined;
    h.summary = undefined;
  });

  it("says the guard is off when no wallet is connected", async () => {
    renderShell();
    expect(await screen.findByRole("status")).toHaveTextContent(/connect a wallet/i);
    expect(screen.getByRole("status")).toHaveTextContent(/spend guard is off/i);
  });

  it("says the guard is off while the on-chain balance loads", async () => {
    h.address = "0x1111111111111111111111111111111111111111";
    renderShell();
    expect(await screen.findByRole("status")).toHaveTextContent(/reading your on-chain balance/i);
  });

  it("says the guard is off when the ledger can't be read — the backend-down case", async () => {
    h.address = "0x1111111111111111111111111111111111111111";
    h.escrow = 5_000_000n;
    h.summary = undefined; // /billing/summary failed
    renderShell();

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/balance can't be read/i);
    expect(status).toHaveTextContent(/spend guard is off/i);
  });

  it("shows no warning once the balance is readable", async () => {
    h.address = "0x1111111111111111111111111111111111111111";
    h.escrow = 5_000_000n;
    h.summary = { total_held: 1 };
    renderShell();

    // The model list arrives async; wait for the panel before judging.
    await waitFor(() => expect(screen.getByLabelText("Prompt")).toBeInTheDocument());
    expect(screen.queryByText(/spend guard is off/i)).not.toBeInTheDocument();
  });
});
