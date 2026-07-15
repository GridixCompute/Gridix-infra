import type { Metadata } from "next";
import Link from "next/link";
import { SiteHeader } from "@/components/marketing/SiteHeader";
import { SiteFooter } from "@/components/marketing/SiteFooter";
import { CodeBlock } from "@/components/provider/CodeBlock";
import { env } from "@/lib/config/env";

export const metadata: Metadata = {
  title: "Documentation",
  description:
    "Run your first GPU compute job on GRIDIX: register, fund escrow, submit a container, and download the result — pay per second in USDC.",
};

const API = env.apiUrl;

const TOC = [
  { id: "quickstart", label: "Quickstart" },
  { id: "job-container", label: "Job container" },
  { id: "api", label: "API reference" },
  { id: "pricing", label: "Pricing" },
  { id: "faq", label: "FAQ" },
];

export default function DocsPage() {
  return (
    <div className="min-h-dvh bg-[var(--color-void)]">
      <SiteHeader />
      <main className="mx-auto grid max-w-6xl gap-10 px-5 py-12 lg:grid-cols-[200px_1fr]">
        {/* Sticky table of contents */}
        <aside className="hidden lg:block">
          <nav aria-label="On this page" className="sticky top-24 space-y-1 text-sm">
            <div className="mb-2 text-xs font-medium tracking-wide text-[var(--color-ink-faint)] uppercase">
              On this page
            </div>
            {TOC.map((t) => (
              <a
                key={t.id}
                href={`#${t.id}`}
                className="block rounded-[var(--radius-sm)] px-2 py-1 text-[var(--color-ink-soft)] hover:bg-[var(--color-panel)] hover:text-[var(--color-ink)]"
              >
                {t.label}
              </a>
            ))}
          </nav>
        </aside>

        <div className="max-w-3xl min-w-0 space-y-14">
          <header className="space-y-3">
            <h1 className="text-3xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
              Documentation
            </h1>
            <p className="text-[var(--color-ink-soft)]">
              GRIDIX runs your containerised workloads on a decentralized GPU network. You pay per
              second in USDC; every result and payment settles on-chain. This page takes you from
              zero to your first completed job.
            </p>
          </header>

          {/* Quickstart */}
          <Section id="quickstart" title="Quickstart">
            <p>Four steps from nothing to a finished job.</p>

            <Step n={1} title="Create an account">
              <p>
                Register to get an API key. It&apos;s shown once — store it somewhere safe; it
                authenticates every request.
              </p>
              <CodeBlock
                code={`curl -X POST ${API}/developers \\
  -H "Content-Type: application/json" \\
  -d '{"name": "Acme AI"}'
# → { "id": "...", "name": "Acme AI", "api_key": "grdx_..." }`}
              />
              <p className="text-sm text-[var(--color-ink-faint)]">
                Prefer a UI?{" "}
                <Link href="/register" className="text-[var(--color-signal-bright)] underline">
                  Create your account
                </Link>{" "}
                in the dashboard instead.
              </p>
            </Step>

            <Step n={2} title="Fund your escrow">
              <p>
                Jobs are paid from an on-chain USDC escrow. Deposit from your wallet on the{" "}
                <Link href="/billing" className="text-[var(--color-signal-bright)] underline">
                  Billing
                </Link>{" "}
                page. No balance, no compute — the contract enforces it. GRIDIX settles on Sepolia
                today.
              </p>
            </Step>

            <Step n={3} title="Submit a job">
              <p>
                Point GRIDIX at a container image and the resources it needs. Worst-case cost is
                escrowed now and reconciled when the job settles.
              </p>
              <CodeBlock
                code={`curl -X POST ${API}/jobs \\
  -H "Authorization: Bearer grdx_your_key" \\
  -H "Content-Type: application/json" \\
  -d '{
    "image_ref": "ghcr.io/acme/trainer:latest",
    "resource_spec": { "cpu_cores": 1, "memory_mb": 2048, "gpu": true, "gpu_vram_mb": 16000 },
    "timeout_seconds": 600,
    "args": { "command": ["python", "train.py"] }
  }'
# → a Job with status "queued" and an escrow_amount`}
              />
              <p className="text-sm text-[var(--color-ink-faint)]">
                Or use the{" "}
                <Link href="/jobs/new" className="text-[var(--color-signal-bright)] underline">
                  Submit a job
                </Link>{" "}
                form, which shows a live cost estimate as you fill it in.
              </p>
            </Step>

            <Step n={4} title="Get your result">
              <p>
                Poll the job until it reaches <Code>completed</Code>, then download the result blob.
              </p>
              <CodeBlock
                code={`# status: queued → assigned → running → completed
curl ${API}/jobs/JOB_ID -H "Authorization: Bearer grdx_your_key"

# download the result once completed
curl ${API}/jobs/JOB_ID/result -H "Authorization: Bearer grdx_your_key" -o result.bin`}
              />
              <p>
                Unused escrow is refunded automatically — you&apos;re only charged for the compute
                actually used. Watch it live on your{" "}
                <Link href="/dashboard" className="text-[var(--color-signal-bright)] underline">
                  dashboard
                </Link>
                .
              </p>
            </Step>
          </Section>

          {/* Job container */}
          <Section id="job-container" title="Packaging a job">
            <p>
              A job is any Docker image. The agent runs it in a hardened, throwaway container: no
              network by default, dropped capabilities, read-only root, non-root user, and a
              wall-clock timeout. Design your image to that contract:
            </p>
            <ul className="ml-5 list-disc space-y-1.5 text-[var(--color-ink-soft)]">
              <li>
                Read inputs and write outputs under <Code>/workspace</Code>; the agent collects what
                you leave there as the result.
              </li>
              <li>
                Exit <Code>0</Code> on success. A non-zero exit marks the job failed and refunds the
                escrow.
              </li>
              <li>
                Network egress is <strong>off</strong> unless you set{" "}
                <Code>allow_egress: true</Code>. Bake dependencies into the image.
              </li>
              <li>
                For GPU jobs, declare <Code>gpu: true</Code> and the <Code>gpu_vram_mb</Code> you
                need; the scheduler matches a provider whose card covers it.
              </li>
            </ul>
            <CodeBlock
              code={`# A minimal GPU job image
FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04
WORKDIR /workspace
COPY train.py .
RUN pip install --no-cache-dir torch
# Write results to /workspace; exit 0 on success.
ENTRYPOINT ["python", "train.py"]`}
            />
          </Section>

          {/* API reference */}
          <Section id="api" title="API reference">
            <p>
              Base URL <Code>{API}</Code>. Authenticate every request with your key as a bearer
              token:
            </p>
            <CodeBlock code={`Authorization: Bearer grdx_your_key`} />
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="text-xs tracking-wide text-[var(--color-ink-faint)] uppercase">
                    <th className="py-2 pr-4 font-medium">Method</th>
                    <th className="py-2 pr-4 font-medium">Path</th>
                    <th className="py-2 font-medium">Purpose</th>
                  </tr>
                </thead>
                <tbody className="align-top">
                  {[
                    ["POST", "/developers", "Create an account, get an API key (once)"],
                    ["POST", "/jobs", "Submit a job; escrows worst-case cost"],
                    ["GET", "/jobs", "List your jobs"],
                    ["GET", "/jobs/{id}", "Fetch one job's status and cost"],
                    ["GET", "/jobs/{id}/result", "Download the result blob (when completed)"],
                    ["GET", "/jobs/{id}/audit", "Full audit trail: attempts + ledger"],
                  ].map(([m, p, d]) => (
                    <tr key={p} className="border-t border-[var(--color-hairline)]">
                      <td className="py-2 pr-4 font-[var(--font-mono)] text-[var(--color-signal-bright)]">
                        {m}
                      </td>
                      <td className="py-2 pr-4 font-[var(--font-mono)] text-[var(--color-ink)]">
                        {p}
                      </td>
                      <td className="py-2 text-[var(--color-ink-soft)]">{d}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-sm text-[var(--color-ink-faint)]">
              Errors are JSON with a <Code>detail</Code> message and the right HTTP status (401
              unauthenticated, 403 insufficient balance, 422 validation, 429 rate-limited).
            </p>
          </Section>

          {/* Pricing */}
          <Section id="pricing" title="Pricing">
            <p>Transparent, per-second, and auditable against the on-chain ledger.</p>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <tbody>
                  {[
                    ["Compute", "1.00 USDC per CPU-core-minute"],
                    ["GPU multiplier", "×4 on the compute rate"],
                    ["Protocol fee", "2.5% of compute, at settlement"],
                    ["Data movement", "billed per byte of egress/result"],
                    ["Refunds", "unused escrow returned automatically"],
                  ].map(([k, v]) => (
                    <tr key={k} className="border-t border-[var(--color-hairline)]">
                      <td className="py-2 pr-6 text-[var(--color-ink-faint)]">{k}</td>
                      <td className="py-2 text-[var(--color-ink)]">{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="rounded-[var(--radius-md)] border border-[var(--color-hairline)] bg-[var(--color-panel)] p-4 text-sm text-[var(--color-ink-soft)]">
              <div className="mb-1 font-medium text-[var(--color-ink)]">Worked example</div>1 CPU
              core for 5 minutes = 5.00 USDC compute + 0.125 USDC protocol fee ={" "}
              <span className="text-[var(--color-signal-bright)]">5.125 USDC</span>. A GPU job at
              the same shape would escrow 20.00 USDC compute. You&apos;re charged for actual
              runtime, not the timeout.
            </div>
          </Section>

          {/* FAQ */}
          <Section id="faq" title="FAQ">
            <Faq q="Which chain and token?">
              GRIDIX settles in USDC on Ethereum Sepolia today. Deposits, withdrawals, and provider
              settlement are all on-chain; contract addresses are linked from the landing page.
            </Faq>
            <Faq q="How do refunds work?">
              At submit we escrow the worst-case cost. When the job settles we charge only the
              compute actually used and refund the remainder to your balance — a failed or timed-out
              job is fully refunded.
            </Faq>
            <Faq q="What is redundancy (K)?">
              For high-value jobs you can run the same work on multiple providers (K &gt; 1). The
              result is accepted only when a majority agree; a dishonest provider is slashed. You
              see every provider&apos;s outcome on the job detail page.
            </Faq>
            <Faq q="Is my data private?">
              Jobs run in isolated, network-off containers. Higher tiers encrypt data at rest and
              can require a trusted execution environment. Choose the data tier per job.
            </Faq>
            <Faq q="Do you support GPUs?">
              Yes. Declare <Code>gpu: true</Code> and the VRAM you need; the scheduler matches a
              provider whose measured, benchmarked card covers it.
            </Faq>
          </Section>

          <div className="rounded-[var(--radius-lg)] border border-[var(--color-signal-dim)] bg-[var(--color-signal-glow)] p-6 text-center">
            <div className="text-lg font-[var(--font-display)] font-semibold text-[var(--color-ink)]">
              Ready to run your first job?
            </div>
            <div className="mt-4 flex justify-center gap-3">
              <Link
                href="/register"
                className="rounded-[var(--radius-sm)] bg-[var(--color-signal)] px-4 py-2 text-sm font-medium text-black"
              >
                Create an account
              </Link>
              <Link
                href="/jobs/new"
                className="rounded-[var(--radius-sm)] border border-[var(--color-hairline-strong)] px-4 py-2 text-sm text-[var(--color-ink)]"
              >
                Submit a job
              </Link>
            </div>
          </div>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24 space-y-4">
      <h2 className="text-2xl font-[var(--font-display)] font-bold text-[var(--color-ink)]">
        {title}
      </h2>
      <div className="space-y-4 text-[var(--color-ink-soft)]">{children}</div>
    </section>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <h3 className="flex items-center gap-3 text-lg font-semibold text-[var(--color-ink)]">
        <span className="flex h-7 w-7 items-center justify-center rounded-full border border-[var(--color-signal-dim)] bg-[var(--color-signal-glow)] text-sm text-[var(--color-signal-bright)]">
          {n}
        </span>
        {title}
      </h3>
      <div className="space-y-3 pl-10">{children}</div>
    </div>
  );
}

function Faq({ q, children }: { q: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-[var(--color-hairline)] pt-4">
      <h3 className="font-medium text-[var(--color-ink)]">{q}</h3>
      <p className="mt-1.5 text-sm text-[var(--color-ink-soft)]">{children}</p>
    </div>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded bg-[var(--color-panel)] px-1.5 py-0.5 text-[0.85em] font-[var(--font-mono)] text-[var(--color-ink)]">
      {children}
    </code>
  );
}
