import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { escrowAbi, stakingAbi } from "./abis";

/**
 * Anti-drift for the contract ABIs, which nothing else covers.
 *
 * The app's REST types are generated from the backend's OpenAPI and policed by the
 * `openapi-drift` CI job. The contracts are the other half of the boundary and had no such
 * gate — so `escrowAbi` sat declaring `Deposit`/`Withdrawal` while GridixEscrow.sol emits
 * `Deposited`/`Withdrawn`. Nothing failed, because nothing read those events yet.
 *
 * That is the nasty shape of this bug: the event name is hashed into the log's topic0, so a
 * filter on a misspelled event does not throw — it matches zero logs. A deposit history
 * built on it would render "no activity" for a user who had deposited, and look correct
 * while doing it.
 *
 * So this reads the Solidity source and asserts every event we declare actually exists
 * there, with the same argument types. It cannot be fooled by a plausible-looking name.
 */

const CONTRACTS = resolve(__dirname, "../../../../contracts/src");

/** `event Deposited(address indexed developer, uint256 amount);` → name + arg types. */
function eventsInSolidity(file: string): Map<string, string[]> {
  const src = readFileSync(resolve(CONTRACTS, file), "utf8");
  const out = new Map<string, string[]>();
  for (const m of src.matchAll(/^\s*event\s+(\w+)\s*\(([^)]*)\)\s*;/gm)) {
    const [, name, args] = m;
    const types = (args ?? "")
      .split(",")
      .map((a) => a.trim())
      .filter(Boolean)
      .map((a) => a.split(/\s+/)[0]!); // leading token is the type
    out.set(name!, types);
  }
  return out;
}

type AbiEntry = { type: string; name?: string; inputs?: readonly { type: string }[] };

function declaredEvents(abi: readonly unknown[]): AbiEntry[] {
  return (abi as AbiEntry[]).filter((e) => e.type === "event");
}

describe("contract ABIs match the Solidity source", () => {
  it("finds the contracts (guards against this test silently passing on a bad path)", () => {
    expect(eventsInSolidity("GridixEscrow.sol").size).toBeGreaterThan(0);
    expect(eventsInSolidity("GridixStaking.sol").size).toBeGreaterThan(0);
  });

  it("escrowAbi declares only events GridixEscrow actually emits", () => {
    const real = eventsInSolidity("GridixEscrow.sol");
    for (const ev of declaredEvents(escrowAbi)) {
      expect(
        real.has(ev.name!),
        `escrowAbi declares "${ev.name}", which GridixEscrow.sol does not emit. ` +
          `It emits: ${[...real.keys()].join(", ")}. A filter on a wrong name matches nothing, silently.`,
      ).toBe(true);
      expect(ev.inputs?.map((i) => i.type)).toEqual(real.get(ev.name!));
    }
  });

  it("stakingAbi declares only events GridixStaking actually emits", () => {
    const real = eventsInSolidity("GridixStaking.sol");
    for (const ev of declaredEvents(stakingAbi)) {
      expect(
        real.has(ev.name!),
        `stakingAbi declares "${ev.name}", which GridixStaking.sol does not emit. ` +
          `It emits: ${[...real.keys()].join(", ")}.`,
      ).toBe(true);
      expect(ev.inputs?.map((i) => i.type)).toEqual(real.get(ev.name!));
    }
  });

  it("pins the two names the bug got wrong", () => {
    const names = declaredEvents(escrowAbi).map((e) => e.name);
    expect(names).toContain("Deposited");
    expect(names).toContain("Withdrawn");
    expect(names).not.toContain("Deposit");
    expect(names).not.toContain("Withdrawal");
  });
});
