import { Badge } from "@/components/ui/Badge";
import { AddressDisplay } from "./AddressDisplay";

export type TxState = "idle" | "signing" | "pending" | "confirmed" | "failed";

/**
 * On-chain transaction status (Session 2.4 / 5.4). NEVER shows "confirmed" until
 * the chain actually confirms — pending shows the hash + explorer link.
 */
const CONFIG: Record<
  Exclude<TxState, "idle">,
  { label: string; tone: Parameters<typeof Badge>[0]["tone"]; live?: boolean }
> = {
  signing: { label: "Waiting for signature", tone: "info" },
  pending: { label: "Pending confirmation", tone: "warning", live: true },
  confirmed: { label: "Confirmed", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
};

export function TxStatus({ state, hash }: { state: TxState; hash?: string }) {
  if (state === "idle") return null;
  const c = CONFIG[state];
  return (
    <span className="inline-flex items-center gap-2">
      <Badge tone={c.tone}>
        <span
          className={c.live ? "animate-pulse-dot h-1.5 w-1.5 rounded-full bg-current" : "hidden"}
          aria-hidden="true"
        />
        {c.label}
      </Badge>
      {hash && <AddressDisplay value={hash} kind="tx" />}
    </span>
  );
}
