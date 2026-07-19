import type { Page } from "@playwright/test";

/**
 * A fake wallet + fake chain, so the wallet paths can be tested hermetically.
 *
 * Two halves are needed, because the app talks to the chain two different ways:
 *
 *  - WRITES and connection go through the injected wallet (`window.ethereum`), which wagmi's
 *    `injected()` connector finds. That is the EIP-1193 provider installed below.
 *  - READS (`useReadContract` → balanceOf, allowance) do NOT touch the wallet. They go over
 *    wagmi's configured HTTP transport straight to the RPC. So the RPC URL is intercepted
 *    too — without that, an "offline" test would quietly hit real Sepolia and pass or fail
 *    on someone else's chain state.
 */

export const TEST_ADDRESS = "0x1111111111111111111111111111111111111111";

export const SEPOLIA_HEX = "0xaa36a7"; // 11155111
const OTHER_CHAIN_HEX = "0x1"; // mainnet — used for the wrong-network path
export const TX_HASH = "0x" + "ab".repeat(32);
/** A well-formed 65-byte secp256k1 signature. Never verified here — /auth/verify is mocked. */
export const SIGNATURE = "0x" + "11".repeat(65);

/** ABI-encode a uint256 as a 32-byte return value. */
function uint256(value: bigint): string {
  return "0x" + value.toString(16).padStart(64, "0");
}

export type WalletOptions = {
  /** Start on the wrong network, to drive the network guard. */
  wrongChain?: boolean;
  /** Make the wallet refuse to sign, as a user clicking "reject" does. */
  rejectTx?: boolean;
  /** Refuse the SIWE `personal_sign` prompt — the sign-in equivalent of rejectTx. */
  rejectSign?: boolean;
  /**
   * What every `balanceOf` returns, in base units (6dp) — escrow AND wallet USDC alike.
   *
   * They cannot be told apart here. Both use the same selector, so the only discriminator is
   * the destination address, and the test process cannot know which one the build used: the
   * addresses come from env with fallbacks, and `.env.local` is gitignored — so CI builds
   * with `env.ts`'s defaults while a laptop builds with whatever is in its own file. A
   * hardcoded copy would silently answer the wrong contract on one of the two.
   *
   * If a test ever needs the two to differ, pass the addresses in explicitly rather than
   * guessing them here.
   */
  balanceOf?: bigint;
  /** ERC-20 allowance already granted to the escrow. */
  allowance?: bigint;
};

/**
 * Install the fake wallet BEFORE any app script runs, and intercept the RPC.
 * Must be called before `page.goto`.
 */
export async function mockWallet(page: Page, opts: WalletOptions = {}): Promise<void> {
  const {
    wrongChain = false,
    rejectTx = false,
    rejectSign = false,
    balanceOf = 25_000_000n,
    allowance = 0n,
  } = opts;

  await page.addInitScript(
    ({ address, chainHex, reject, rejectSignature, txHash, signature }) => {
      const listeners: Record<string, ((...a: unknown[]) => void)[]> = {};
      let chain = chainHex;

      const provider = {
        isMetaMask: true,
        request: async ({ method }: { method: string; params?: unknown[] }) => {
          switch (method) {
            case "eth_requestAccounts":
            case "eth_accounts":
              return [address];
            case "eth_chainId":
              return chain;
            case "wallet_switchEthereumChain":
              // The real wallet emits chainChanged; wagmi listens for it.
              chain = "0xaa36a7";
              for (const cb of listeners["chainChanged"] ?? []) cb(chain);
              return null;
            case "personal_sign":
              // SIWE sign-in. Rejecting looks exactly like rejecting a transaction.
              if (rejectSignature) {
                const err = new Error("User rejected the request.") as Error & { code: number };
                err.code = 4001;
                throw err;
              }
              return signature;
            case "eth_estimateGas":
              return "0x5208";
            case "eth_sendTransaction":
              if (reject) {
                // Shape of a real user rejection (EIP-1193 error 4001).
                const err = new Error("User rejected the request.") as Error & { code: number };
                err.code = 4001;
                throw err;
              }
              return txHash;
            default:
              throw Object.assign(new Error(`unhandled ${method}`), { code: -32601 });
          }
        },
        on: (event: string, cb: (...a: unknown[]) => void) => {
          (listeners[event] ??= []).push(cb);
        },
        removeListener: (event: string, cb: (...a: unknown[]) => void) => {
          listeners[event] = (listeners[event] ?? []).filter((f) => f !== cb);
        },
      };

      Object.defineProperty(window, "ethereum", { value: provider, writable: true });
    },
    {
      address: TEST_ADDRESS,
      chainHex: wrongChain ? OTHER_CHAIN_HEX : SEPOLIA_HEX,
      reject: rejectTx,
      rejectSignature: rejectSign,
      txHash: TX_HASH,
      signature: SIGNATURE,
    },
  );

  // The read path: wagmi's http transport. Matched by "not our own origin" rather than by
  // RPC hostname, because the hostname differs between environments — `.env.local` is
  // gitignored, so CI builds with env.ts's default RPC and a laptop builds with its own. A
  // host-specific glob would silently stop matching on one of them, the reads would hit the
  // real network, and the test would pass or fail on somebody else's chain.
  await page.route(
    (url) => url.hostname !== "localhost" && url.hostname !== "127.0.0.1",
    async (route) => {
      // The RPC is cross-origin, so the browser needs CORS headers to hand the body to the
      // page. route.fulfill does not add them: without these the response is blocked, the
      // read never resolves, and — because nothing throws — the UI just renders 0 forever.
      const cors = {
        "access-control-allow-origin": "*",
        "access-control-allow-headers": "*",
        "access-control-allow-methods": "POST, OPTIONS",
      };
      if (route.request().method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers: cors });
        return;
      }
      const body = route.request().postDataJSON() as
        | { id: number; method: string; params?: unknown[] }
        | { id: number; method: string; params?: unknown[] }[];
      const one = (req: { id: number; method: string; params?: unknown[] }) => {
        const ok = (result: unknown) => ({ jsonrpc: "2.0", id: req.id, result });
        switch (req.method) {
          case "eth_chainId":
            return ok(SEPOLIA_HEX);
          case "eth_blockNumber":
            return ok("0x1");
          case "eth_call": {
            const data = String((req.params as [{ data?: string }])[0]?.data ?? "");
            // allowance(owner,spender) — the one read we can identify by selector alone.
            if (data.startsWith("0xdd62ed3e")) return ok(uint256(allowance));
            return ok(uint256(balanceOf)); // every balanceOf; see WalletOptions.balanceOf
          }
          case "eth_getTransactionReceipt":
            return ok({
              transactionHash: TX_HASH,
              blockNumber: "0x1",
              blockHash: "0x" + "cd".repeat(32),
              status: "0x1",
              gasUsed: "0x5208",
              cumulativeGasUsed: "0x5208",
              logs: [],
              logsBloom: "0x" + "00".repeat(256),
              transactionIndex: "0x0",
              from: TEST_ADDRESS,
              to: TEST_ADDRESS,
              contractAddress: null,
              effectiveGasPrice: "0x1",
              type: "0x2",
            });
          case "eth_getBlockByNumber":
            return ok({
              number: "0x1",
              hash: "0x" + "cd".repeat(32),
              timestamp: "0x1",
              baseFeePerGas: "0x1",
            });
          default:
            return {
              jsonrpc: "2.0",
              id: req.id,
              error: { code: -32601, message: `e2e: unmocked ${req.method}` },
            };
        }
      };
      const payload = Array.isArray(body) ? body.map(one) : one(body);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: cors,
        body: JSON.stringify(payload),
      });
    },
  );
}
