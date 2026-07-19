import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ImagePanel } from "./ImagePanel";
import { MOCK_MODELS } from "@/lib/inference/mock";
import type { ImageParams } from "@/lib/inference/types";

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

const IMAGE_MODEL = MOCK_MODELS.find((m) => m.kind === "image")!;
const PARAMS: ImageParams = { size: "768x768", steps: 20, seed: null };

describe("ImagePanel — balance gate", () => {
  it("blocks when one image costs more than the balance", () => {
    // One micro-USDC short of the per-image price.
    const justShort = BigInt(IMAGE_MODEL.pricePerImage! - 1);
    render(<ImagePanel model={IMAGE_MODEL} params={PARAMS} availableBase={justShort} />);

    expect(screen.getByRole("alert")).toHaveTextContent(/more than your balance/i);
    expect(screen.getByRole("link", { name: /top up/i })).toHaveAttribute("href", "/billing");
    expect(screen.getByLabelText("Image prompt")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Generate" })).toBeDisabled();
  });

  it("allows when the balance covers exactly one image", () => {
    // Exactly the price: affordable. An off-by-one here would block a user who can pay.
    const exact = BigInt(IMAGE_MODEL.pricePerImage!);
    render(<ImagePanel model={IMAGE_MODEL} params={PARAMS} availableBase={exact} />);

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

  it("shows the flat per-image price, which size does not change", () => {
    const { rerender } = render(
      <ImagePanel
        model={IMAGE_MODEL}
        params={{ ...PARAMS, size: "512x512" }}
        availableBase={null}
      />,
    );
    const small = screen.getByText(/per image/i).textContent;

    rerender(
      <ImagePanel
        model={IMAGE_MODEL}
        params={{ ...PARAMS, size: "1024x1024" }}
        availableBase={null}
      />,
    );
    expect(screen.getByText(/per image/i).textContent).toEqual(small);
  });
});
