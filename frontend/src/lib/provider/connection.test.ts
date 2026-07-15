import { describe, it, expect } from "vitest";
import { agentConnection } from "./connection";

const NOW = Date.parse("2026-07-15T12:00:00Z");

describe("agentConnection", () => {
  it("reports never-connected when there is no record", () => {
    const c = agentConnection(undefined, NOW);
    expect(c.everConnected).toBe(false);
    expect(c.online).toBe(false);
    expect(c.label).toBe("Not connected");
  });

  it("reports never-connected when connected_at and last_seen are null", () => {
    const c = agentConnection({ connected_at: null, last_seen: null }, NOW);
    expect(c.everConnected).toBe(false);
    expect(c.online).toBe(false);
  });

  it("is online when last_seen is within the heartbeat window", () => {
    const c = agentConnection(
      { connected_at: "2026-07-15T11:00:00Z", last_seen: "2026-07-15T11:59:30Z" },
      NOW,
    );
    expect(c.everConnected).toBe(true);
    expect(c.online).toBe(true);
    expect(c.label).toBe("Online");
  });

  it("is offline when it connected before but has gone silent", () => {
    const c = agentConnection(
      { connected_at: "2026-07-15T10:00:00Z", last_seen: "2026-07-15T11:58:00Z" },
      NOW,
    );
    expect(c.everConnected).toBe(true);
    expect(c.online).toBe(false);
    expect(c.label).toBe("Offline");
  });

  it("treats exactly-at-the-window edge as online", () => {
    const c = agentConnection(
      { connected_at: "2026-07-15T11:00:00Z", last_seen: "2026-07-15T11:59:15Z" }, // 45s ago
      NOW,
    );
    expect(c.online).toBe(true);
  });
});
