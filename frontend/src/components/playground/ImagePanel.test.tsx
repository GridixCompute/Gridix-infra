import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ImagePanel } from "./ImagePanel";
import { MOCK_MODELS } from "@/lib/inference/mock";
import { toBaseUnits } from "@/lib/format/usdc";
import type { ImageParams } from "@/lib/inference/params";

/**
 * The image balance gate (Session 5.2), covered here for the same reason as ChatPanel's: the
 * gate needs a real balance (on-chain escrow + backend ledger), which the dev environment
 * cannot supply, so the browser pass only ever exercises the balance-unknown path.
 *
 * Image pricing differs from chat in a way worth pinning: it is per image and known exactly
 * before sending, so the gate compares the real price rather than a worst-case estimate.
 * Both directions are asserted — a block-only test proves nothing if the panel is blocked
 * for an unrelated reason.
 */

const IMAGE_MODEL = MOCK_MODELS.find((m) => m.modality === "image")!;
const PARAMS: ImageParams = { seed: null };
/** The rate card is a decimal-USDC string; the gate compares base units. */
const PRICE_BASE = toBaseUnits(IMAGE_MODEL.usdc_per_image);

describe("ImagePanel — balance gate", () => {
  it("blocks when one image costs more than the balance", () => {
    // One base unit short of the per-image price.
    render(<ImagePanel model={IMAGE_MODEL} params={PARAMS} availableBase={PRICE_BASE - 1n} />);

    expect(screen.getByRole("alert")).toHaveTextContent(/more than your balance/i);
    expect(screen.getByRole("link", { name: /top up/i })).toHaveAttribute("href", "/billing");
    expect(screen.getByLabelText("Image prompt")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Generate" })).toBeDisabled();
  });

  it("allows when the balance covers exactly one image", () => {
    // Exactly the price: affordable. An off-by-one here would block a user who can pay.
    render(<ImagePanel model={IMAGE_MODEL} params={PARAMS} availableBase={PRICE_BASE} />);

    expect(screen.queryByText(/more than your balance/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Image prompt")).toBeEnabled();
  });

  it("does not gate when the balance is unknown", () => {
    render(<ImagePanel model={IMAGE_MODEL} params={PARAMS} availableBase={null} />);
    expect(screen.queryByText(/more than your balance/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Image prompt")).toBeEnabled();
  });

  it("blocks a model no provider is serving", () => {
    const offline = { ...IMAGE_MODEL, available: false };
    render(<ImagePanel model={offline} params={PARAMS} availableBase={1_000_000n} />);

    expect(screen.getByRole("alert")).toHaveTextContent(/no provider is serving/i);
    expect(screen.getByLabelText("Image prompt")).toBeDisabled();
  });

  it("shows the price from the rate card, not an invented one", () => {
    // `usdc_per_image` is "0.01" on the wire. The panel must render that, in USDC — the
    // predecessor read a per-image price as integer micro-USDC and would have shown 0.000010.
    render(<ImagePanel model={IMAGE_MODEL} params={PARAMS} availableBase={null} />);
    expect(screen.getByText(/per image/i).textContent).toContain("0.01");
  });
});
