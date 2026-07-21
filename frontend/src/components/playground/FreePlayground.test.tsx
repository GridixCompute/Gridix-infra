import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FreePlayground } from "./FreePlayground";

/**
 * The playground is public: chat works with no account, images ask for a wallet.
 *
 * Both halves are asserted, because the interesting failures are asymmetric. A build that
 * demanded a wallet for chat would still pass every image test; a build that hid the image
 * tab when signed out would still pass every chat test. So the tests check that chat needs
 * nothing AND that the image tab invites rather than hides or errors.
 */

const connected = vi.fn<() => { isConnected: boolean; address?: string }>(() => ({
  isConnected: false,
  address: undefined,
}));
vi.mock("wagmi", () => ({ useAccount: () => connected() }));
vi.mock("@/components/chain/ConnectWallet", () => ({
  ConnectWallet: () => <button>Connect wallet</button>,
}));

const streamMock = vi.fn();
const quotaMock = vi.fn();
const generateMock = vi.fn();
vi.mock("@/lib/public/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/public/client")>();
  return {
    ...actual,
    streamPublicChat: (...a: unknown[]) => streamMock(...a),
    fetchImageQuota: (...a: unknown[]) => quotaMock(...a),
    generatePublicImage: (...a: unknown[]) => generateMock(...a),
  };
});

function streamOf(events: unknown[]) {
  return async function* () {
    for (const e of events) yield e;
  };
}

const log = () => screen.getByRole("log", { name: "Conversation" });

beforeEach(() => {
  streamMock.mockReset();
  quotaMock.mockReset().mockResolvedValue(null);
  generateMock.mockReset();
  connected.mockReturnValue({ isConnected: false, address: undefined });
});
afterEach(() => vi.clearAllMocks());

describe("chat is open to anyone", () => {
  it("sends a message with no wallet and no account", async () => {
    streamMock.mockImplementation(streamOf([{ kind: "delta", content: "hello there" }]));
    const user = userEvent.setup();
    render(<FreePlayground />);

    await user.type(screen.getByLabelText("Prompt"), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await within(log()).findByText(/hello there/);
    // Nothing asked the visitor to connect anything.
    expect(screen.queryByText(/connect a wallet/i)).not.toBeInTheDocument();
  });

  it("surfaces the rate limit as a readable message, not a crash", async () => {
    const { PublicApiError } = await import("@/lib/public/client");
    streamMock.mockImplementation(() => {
      throw new PublicApiError(429, "You're sending messages very fast. Wait a moment.");
    });
    const user = userEvent.setup();
    render(<FreePlayground />);

    await user.type(screen.getByLabelText("Prompt"), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/very fast/i));
  });
});

describe("the image tab when signed out", () => {
  it("invites a wallet connection rather than erroring or hiding", async () => {
    const user = userEvent.setup();
    render(<FreePlayground />);
    await user.click(screen.getByRole("tab", { name: "image" }));

    // An invitation: what to do, and what you get for doing it.
    expect(await screen.findByText(/connect a wallet to generate images/i)).toBeInTheDocument();
    expect(screen.getByText(/5 per day/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /connect wallet/i })).toBeInTheDocument();
    // Not an error state — nothing is broken.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not hide the tab", () => {
    render(<FreePlayground />);
    expect(screen.getByRole("tab", { name: "image" })).toBeInTheDocument();
  });
});

describe("the image tab once connected", () => {
  beforeEach(() => {
    connected.mockReturnValue({ isConnected: true, address: "0xabc" });
    quotaMock.mockResolvedValue({
      limit: 5,
      used: 2,
      remaining: 3,
      resets: "00:00 UTC",
      available: true,
    });
  });

  it("shows how many are left, so nobody discovers the limit by hitting it", async () => {
    const user = userEvent.setup();
    render(<FreePlayground />);
    await user.click(screen.getByRole("tab", { name: "image" }));

    expect(await screen.findByTestId("image-quota")).toHaveTextContent("3 of 5");
    expect(screen.getByText(/resets/i)).toHaveTextContent("00:00 UTC");
  });

  it("generates, and refreshes the remaining count afterwards", async () => {
    generateMock.mockResolvedValue([{ url: "https://cdn.test/a.png" }]);
    const user = userEvent.setup();
    render(<FreePlayground />);
    await user.click(screen.getByRole("tab", { name: "image" }));
    await screen.findByTestId("image-quota");

    quotaMock.mockResolvedValue({
      limit: 5,
      used: 3,
      remaining: 2,
      resets: "00:00 UTC",
      available: true,
    });
    await user.type(screen.getByLabelText("Image prompt"), "a globe");
    await user.click(screen.getByRole("button", { name: "Generate" }));

    await waitFor(() => expect(screen.getByTestId("image-quota")).toHaveTextContent("2 of 5"));
    expect(generateMock).toHaveBeenCalledWith("a globe");
  });

  it("shows a refused prompt's reason, and re-reads the allowance", async () => {
    // A refusal must not silently look like a failed request — and it does not spend an
    // image, so the counter is re-read rather than assumed to have moved.
    const { PublicApiError } = await import("@/lib/public/client");
    generateMock.mockRejectedValue(new PublicApiError(400, "That prompt was refused."));
    const user = userEvent.setup();
    render(<FreePlayground />);
    await user.click(screen.getByRole("tab", { name: "image" }));
    await screen.findByTestId("image-quota");

    await user.type(screen.getByLabelText("Image prompt"), "something");
    await user.click(screen.getByRole("button", { name: "Generate" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/refused/i));
    expect(screen.getByTestId("image-quota")).toHaveTextContent("3 of 5");
  });

  it("blocks generating once the day's allowance is spent", async () => {
    quotaMock.mockResolvedValue({
      limit: 5,
      used: 5,
      remaining: 0,
      resets: "00:00 UTC",
      available: true,
    });
    const user = userEvent.setup();
    render(<FreePlayground />);
    await user.click(screen.getByRole("tab", { name: "image" }));

    await waitFor(() => expect(screen.getByTestId("image-quota")).toHaveTextContent("0 of 5"));
    expect(screen.getByLabelText("Image prompt")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Generate" })).toBeDisabled();
  });
});
