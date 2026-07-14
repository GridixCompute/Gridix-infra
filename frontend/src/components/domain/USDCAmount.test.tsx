import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { USDCAmount } from "./USDCAmount";

describe("<USDCAmount>", () => {
  it("renders base units exactly to 6 decimals", () => {
    render(<USDCAmount base={12_500_000n} />);
    expect(screen.getByText("12.50 USDC")).toBeInTheDocument();
  });

  it("renders the smallest unit without losing precision", () => {
    render(<USDCAmount base={1n} />);
    expect(screen.getByText("0.000001 USDC")).toBeInTheDocument();
  });

  it("renders API decimal amounts and can hide the symbol", () => {
    const { rerender } = render(<USDCAmount amount={86.4} />);
    expect(screen.getByText("86.40 USDC")).toBeInTheDocument();
    rerender(<USDCAmount amount={86.4} symbol={false} />);
    expect(screen.getByText("86.40")).toBeInTheDocument();
  });
});
