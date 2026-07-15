import type { Provider } from "@/lib/api/types";

/**
 * Derive an agent's live connection state from its provider record (Sesi 11.2).
 * The backend flags a provider unreachable once `last_seen` ages past the
 * connection timeout (default 30s, always > 2× the 10s heartbeat), so a 45s
 * window keeps a healthy, heartbeating agent green without flapping.
 */
const ONLINE_WINDOW_MS = 45_000;

export type AgentConnection = {
  /** Has the agent ever polled the coordinator? */
  everConnected: boolean;
  /** Is it heartbeating right now? */
  online: boolean;
  label: string;
  title: string;
};

export function agentConnection(
  provider: Pick<Provider, "connected_at" | "last_seen"> | undefined | null,
  now: number = Date.now(),
): AgentConnection {
  const everConnected = !!provider?.connected_at || !!provider?.last_seen;
  const lastSeenMs = provider?.last_seen ? Date.parse(provider.last_seen) : NaN;
  const online = Number.isFinite(lastSeenMs) && now - lastSeenMs <= ONLINE_WINDOW_MS;

  if (!everConnected) {
    return {
      everConnected: false,
      online: false,
      label: "Not connected",
      title: "Your agent has never contacted the coordinator. Follow onboarding to connect it.",
    };
  }
  if (online) {
    return { everConnected: true, online: true, label: "Online", title: "Agent is heartbeating." };
  }
  return {
    everConnected: true,
    online: false,
    label: "Offline",
    title: "Agent connected before but isn't heartbeating now.",
  };
}
