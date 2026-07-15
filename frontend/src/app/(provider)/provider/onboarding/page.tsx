"use client";

import Link from "next/link";
import { Card, CardBody, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { CodeBlock } from "@/components/provider/CodeBlock";
import { Timestamp } from "@/components/domain/Timestamp";
import { useProviderMe } from "@/lib/hooks/useProvider";
import { agentConnection } from "@/lib/provider/connection";
import { env } from "@/lib/config/env";

const ENV_ROWS: Array<[string, string, string]> = [
  ["GRIDIX_API_URL", env.apiUrl, "Coordinator base URL"],
  ["GRIDIX_PROVIDER_KEY", "grdx_… (from registration)", "Your provider API key — required"],
  ["GRIDIX_ENABLE_GPU", "false", "Attach GPUs to job containers"],
  ["GRIDIX_GPU_DEVICES", "(all visible)", "Pin specific GPUs, e.g. GPU-abc,GPU-def"],
  ["GRIDIX_AGENT_WORKDIR", "/var/lib/gridix-agent", "Per-job scratch (input/output)"],
  ["GRIDIX_RELAY_URL", "(unset)", "Relay tunnel for NAT'd hosts"],
];

export default function OnboardingPage() {
  const { data: provider, isLoading } = useProviderMe();
  const conn = agentConnection(provider);

  const installCmd = `GRIDIX_API_URL=${env.apiUrl} \\
GRIDIX_PROVIDER_KEY=grdx_your_key \\
./install.sh

docker logs -f gridix-agent`;

  const dockerCmd = `docker run -d --restart=always --name gridix-agent \\
  -e GRIDIX_API_URL=${env.apiUrl} \\
  -e GRIDIX_PROVIDER_KEY=grdx_your_key \\
  -e GRIDIX_AGENT_WORKDIR=/var/lib/gridix-agent \\
  -v /var/run/docker.sock:/var/run/docker.sock \\
  -v /var/lib/gridix-agent:/var/lib/gridix-agent \\
  ghcr.io/gridixcompute/gridix-agent:v0.1.1`;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
          Agent onboarding
        </h1>
        <p className="mt-1 text-sm text-[var(--color-ink-faint)]">
          Install the GRIDIX agent on a Linux host with Docker. It polls for jobs and runs each one
          in a hardened, throwaway container.
        </p>
      </div>

      {/* Live connection status */}
      <Card
        className={
          conn.online
            ? "border-[#35c88a55] bg-[#35c88a12]"
            : conn.everConnected
              ? "border-[#ffab3d55] bg-[#ffab3d12]"
              : "border-[var(--color-hairline-strong)]"
        }
      >
        <CardBody className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span
              className={`h-2.5 w-2.5 rounded-full ${
                conn.online ? "bg-[var(--color-success)]" : "bg-[var(--color-ink-disabled)]"
              }`}
              aria-hidden="true"
            />
            <div>
              <div className="font-[var(--font-display)] font-semibold text-[var(--color-ink)]">
                {isLoading ? "Checking…" : conn.online ? "Agent online" : conn.label}
              </div>
              <div className="text-sm text-[var(--color-ink-faint)]">
                {conn.online && provider?.last_seen ? (
                  <>
                    Heartbeating — last seen <Timestamp iso={provider.last_seen} />
                  </>
                ) : conn.everConnected ? (
                  "Connected before, but no heartbeat right now. Check the container is running."
                ) : (
                  "Waiting for your agent's first poll. This page updates automatically."
                )}
              </div>
            </div>
          </div>
          {isLoading ? (
            <Skeleton className="h-6 w-20" />
          ) : conn.online ? (
            <Badge tone="success">Connected</Badge>
          ) : (
            <Badge tone="neutral">Waiting</Badge>
          )}
        </CardBody>
      </Card>

      {/* Step 1 */}
      <Step n={1} title="Prepare the host">
        <p>
          You need a Linux machine with <strong>Docker</strong> installed and running — the agent
          shells out to it to run jobs. Verify with:
        </p>
        <CodeBlock code="docker run --rm hello-world" />
      </Step>

      {/* Step 2 */}
      <Step n={2} title="Install & start the agent">
        <p>
          The installer pulls the published image from GHCR and runs it as a self-restarting
          container. Substitute the key you saved at registration:
        </p>
        <CodeBlock code={installCmd} />
        <p className="text-[var(--color-ink-faint)]">
          Prefer to run it yourself? The equivalent <code>docker run</code>:
        </p>
        <CodeBlock code={dockerCmd} />
        <p className="text-xs text-[var(--color-ink-faint)]">
          Mounting the Docker socket grants host-level control — run the agent only on machines you
          own. If the coordinator runs on the same host, add{" "}
          <code className="font-[var(--font-mono)]">--network host</code>.
        </p>
      </Step>

      {/* Step 3 */}
      <Step n={3} title="Confirm the connection">
        <p>
          Once the agent starts polling, the status banner above flips to{" "}
          <span className="text-[var(--color-success)]">Agent online</span>. Watch the logs if it
          doesn&apos;t:
        </p>
        <CodeBlock code="docker logs -f gridix-agent" />
        <ul className="ml-4 list-disc space-y-1 text-[var(--color-ink-faint)]">
          <li>
            <code>401</code> in the logs → wrong or revoked{" "}
            <code className="font-[var(--font-mono)]">GRIDIX_PROVIDER_KEY</code>.
          </li>
          <li>
            Connection refused → check{" "}
            <code className="font-[var(--font-mono)]">GRIDIX_API_URL</code> is reachable from the
            host.
          </li>
          <li>
            Never turns online → the container exited; run{" "}
            <code className="font-[var(--font-mono)]">docker ps -a</code> and inspect its logs.
          </li>
        </ul>
        <p>
          Then declare your hardware and run the benchmark on the{" "}
          <Link
            href="/provider/hardware"
            className="text-[var(--color-signal-bright)] hover:underline"
          >
            Hardware
          </Link>{" "}
          page so the scheduler can match GPU jobs to you.
        </p>
      </Step>

      {/* Env reference */}
      <Card>
        <CardBody className="space-y-3">
          <CardTitle>Configuration reference</CardTitle>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="text-xs tracking-wide text-[var(--color-ink-faint)] uppercase">
                  <th className="py-2 pr-4 font-medium">Variable</th>
                  <th className="py-2 pr-4 font-medium">Default</th>
                  <th className="py-2 font-medium">Purpose</th>
                </tr>
              </thead>
              <tbody className="align-top">
                {ENV_ROWS.map(([name, def, purpose]) => (
                  <tr key={name} className="border-t border-[var(--color-hairline)]">
                    <td className="py-2 pr-4 font-[var(--font-mono)] text-[var(--color-signal-bright)]">
                      {name}
                    </td>
                    <td className="py-2 pr-4 font-[var(--font-mono)] text-[var(--color-ink-soft)]">
                      {def}
                    </td>
                    <td className="py-2 text-[var(--color-ink-faint)]">{purpose}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardBody className="space-y-3">
        <div className="flex items-center gap-3">
          <span className="flex h-7 w-7 items-center justify-center rounded-full border border-[var(--color-signal-dim)] bg-[var(--color-signal-glow)] text-sm font-semibold text-[var(--color-signal-bright)]">
            {n}
          </span>
          <CardTitle className="!mt-0">{title}</CardTitle>
        </div>
        <div className="space-y-3 text-sm text-[var(--color-ink-soft)]">{children}</div>
      </CardBody>
    </Card>
  );
}
