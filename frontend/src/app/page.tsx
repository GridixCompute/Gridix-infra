import Link from "next/link";
import Image from "next/image";
import { SiteHeader } from "@/components/marketing/SiteHeader";
import { SiteFooter } from "@/components/marketing/SiteFooter";
import { Button } from "@/components/ui/Button";
import { AddressDisplay } from "@/components/domain/AddressDisplay";
import { env } from "@/lib/config/env";

const USE_CASES = ["AI Models", "AI Agents", "Enterprise", "Web3"];

const FEATURES = [
  {
    title: "Run any container",
    body: "Submit a Docker image with a GPU/CPU spec. GRIDIX schedules it onto the network, isolates it (no egress, dropped capabilities, non-root), and streams you the result.",
  },
  {
    title: "Pay per second in USDC",
    body: "Deposit USDC once. Every job holds an escrow, charges the actual compute used, and refunds the rest. Six-decimal exact — the number in the UI equals the number on-chain.",
  },
  {
    title: "Verified, not trusted",
    body: "High-value jobs run redundantly across independent providers and settle by quorum. Dishonest providers are slashed. You audit every debit and credit.",
  },
];

const STEPS = [
  {
    n: "01",
    title: "Deposit USDC",
    body: "Fund your escrow on-chain. No balance, no compute — enforced by the contract.",
  },
  {
    n: "02",
    title: "Submit a job",
    body: "Image, resources, timeout. See the cost estimate before you commit.",
  },
  {
    n: "03",
    title: "Watch it run",
    body: "Live status from queued → assigned → running, pushed in real time.",
  },
  {
    n: "04",
    title: "Collect & settle",
    body: "Download the verified result. The ledger settles to the exact cent.",
  },
];

export default function LandingPage() {
  return (
    <>
      <SiteHeader />
      <main>
        <Hero />
        <UseCaseStrip />
        <Product />
        <HowItWorks />
        <Proof />
        <CtaBand />
      </main>
      <SiteFooter />
    </>
  );
}

function Hero() {
  return (
    <section className="relative overflow-hidden border-b border-[var(--color-hairline)]">
      {/* Ambient brand video, dimmed behind the copy. */}
      <video
        className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-40"
        autoPlay
        muted
        loop
        playsInline
        aria-hidden="true"
        poster="/assets/assets 2.png"
      >
        <source src="/assets/assets video.mp4" type="video/mp4" />
      </video>
      <div className="absolute inset-0 bg-gradient-to-r from-[var(--color-void)] via-[var(--color-void)]/85 to-transparent" />
      <div className="absolute inset-0 bg-gradient-to-t from-[var(--color-void)] to-transparent" />

      <div className="relative mx-auto max-w-6xl px-5 py-24 sm:py-32 lg:py-40">
        <div className="max-w-2xl">
          <span className="inline-flex items-center gap-2 rounded-full border border-[var(--color-signal-dim)] bg-[var(--color-signal-glow)] px-3 py-1 text-xs font-medium tracking-wide text-[var(--color-signal-bright)]">
            <span className="animate-pulse-dot h-1.5 w-1.5 rounded-full bg-[var(--color-signal)]" />
            Live on Sepolia · settlement on-chain
          </span>
          <h1 className="mt-6 text-5xl leading-[1.05] font-[var(--font-display)] font-bold tracking-tight text-[var(--color-ink)] sm:text-6xl lg:text-7xl">
            Compute for
            <br />
            everything <span className="text-glow text-[var(--color-signal)]">AI</span>
          </h1>
          <p className="mt-6 max-w-xl text-lg text-[var(--color-ink-soft)]">
            A decentralized compute network for the next generation of AI infrastructure. Run
            containerized GPU workloads on a trustless grid — and pay only for what you use.
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-4">
            <Link href="/register">
              <Button size="lg">Start building</Button>
            </Link>
            <Link href="/docs#quickstart">
              <Button variant="secondary" size="lg">
                Read the quickstart
              </Button>
            </Link>
          </div>
          <p className="mt-8 text-xs font-[var(--font-mono)] tracking-[0.3em] text-[var(--color-signal-dim)] uppercase">
            Decentralized · Scalable · Limitless
          </p>
        </div>
      </div>
    </section>
  );
}

function UseCaseStrip() {
  return (
    <section className="border-b border-[var(--color-hairline)] bg-[var(--color-abyss)]">
      <div className="mx-auto flex max-w-6xl flex-col items-center gap-6 px-5 py-8 sm:flex-row sm:justify-between">
        <span className="text-xs font-semibold tracking-[0.2em] text-[var(--color-ink-faint)] uppercase">
          Powering the AI economy
        </span>
        <div className="flex flex-wrap items-center justify-center gap-x-10 gap-y-3">
          {USE_CASES.map((u) => (
            <span
              key={u}
              className="text-sm font-[var(--font-display)] font-medium tracking-wide text-[var(--color-ink-soft)]"
            >
              {u}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

function Product() {
  return (
    <section id="product" className="relative border-b border-[var(--color-hairline)]">
      <div className="bg-grid absolute inset-0 opacity-40" aria-hidden="true" />
      <div className="relative mx-auto max-w-6xl px-5 py-24">
        <SectionHeading
          eyebrow="The product"
          title="Infrastructure, not a favor"
          body="Everything below is enforced by code and proven on-chain — not a promise on a marketing page."
        />
        <div className="mt-14 grid gap-5 md:grid-cols-3">
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className="group rounded-[var(--radius-lg)] border border-[var(--color-hairline)] bg-[var(--color-panel)] p-7 transition-colors hover:border-[var(--color-signal-dim)]"
            >
              <div className="mb-5 flex h-10 w-10 items-center justify-center rounded-[var(--radius-sm)] border border-[var(--color-signal-dim)] bg-[var(--color-signal-glow)]">
                <span className="h-3 w-3 rounded-sm bg-[var(--color-signal)] transition-transform group-hover:scale-125" />
              </div>
              <h3 className="text-lg font-[var(--font-display)] font-semibold text-[var(--color-ink)]">
                {f.title}
              </h3>
              <p className="mt-3 text-sm leading-relaxed text-[var(--color-ink-faint)]">{f.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function HowItWorks() {
  return (
    <section id="how" className="border-b border-[var(--color-hairline)] bg-[var(--color-abyss)]">
      <div className="mx-auto max-w-6xl px-5 py-24">
        <SectionHeading
          eyebrow="How it works"
          title="From deposit to result in four steps"
          body="The same flow a stranger follows: fund, submit, watch, collect."
        />
        <div className="mt-14 grid gap-px overflow-hidden rounded-[var(--radius-lg)] border border-[var(--color-hairline)] bg-[var(--color-hairline)] sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s) => (
            <div key={s.n} className="bg-[var(--color-panel)] p-7">
              <span className="text-sm font-[var(--font-mono)] text-[var(--color-signal)]">
                {s.n}
              </span>
              <h3 className="mt-4 text-base font-[var(--font-display)] font-semibold text-[var(--color-ink)]">
                {s.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-[var(--color-ink-faint)]">{s.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Proof() {
  return (
    <section
      id="proof"
      className="relative overflow-hidden border-b border-[var(--color-hairline)]"
    >
      <Image
        src="/assets/assets 4.png"
        alt=""
        fill
        aria-hidden="true"
        className="object-cover opacity-25"
        sizes="100vw"
      />
      <div className="absolute inset-0 bg-[var(--color-void)]/70" />
      <div className="relative mx-auto max-w-6xl px-5 py-24">
        <SectionHeading
          eyebrow="Proof, not claims"
          title="Settlement lives on-chain"
          body="Escrow, staking, and batch settlement are deployed and exercised on Sepolia. The contracts are public — verify them yourself."
        />
        <div className="mt-12 grid gap-5 md:grid-cols-2">
          <ContractCard
            label="GridixEscrow"
            description="Developer USDC escrow — deposit, debit, withdraw."
            address={env.contracts.escrow}
          />
          <ContractCard
            label="GridixStaking"
            description="Provider stake, slashing, and batch settlement."
            address={env.contracts.staking}
          />
        </div>
        <div className="mt-8 grid grid-cols-2 gap-5 sm:grid-cols-4">
          <Stat value="6" label="Job states, one state machine" />
          <Stat value="K>1" label="Redundant quorum settlement" />
          <Stat value="100%" label="Contract test coverage" />
          <Stat value="0" label="Ledger discrepancies under chaos" />
        </div>
      </div>
    </section>
  );
}

function ContractCard({
  label,
  description,
  address,
}: {
  label: string;
  description: string;
  address: string;
}) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-hairline)] bg-[var(--color-panel)]/90 p-6 backdrop-blur">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-[var(--font-display)] font-semibold text-[var(--color-ink)]">
          {label}
        </h3>
        <AddressDisplay value={address} kind="address" />
      </div>
      <p className="mt-2 text-sm text-[var(--color-ink-faint)]">{description}</p>
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div className="tabular text-3xl font-[var(--font-mono)] font-bold text-[var(--color-signal)]">
        {value}
      </div>
      <div className="mt-1 text-xs leading-snug text-[var(--color-ink-faint)]">{label}</div>
    </div>
  );
}

function CtaBand() {
  return (
    <section className="bg-[var(--color-abyss)]">
      <div className="mx-auto max-w-6xl px-5 py-24 text-center">
        <h2 className="mx-auto max-w-2xl text-4xl font-[var(--font-display)] font-bold tracking-tight text-[var(--color-ink)] sm:text-5xl">
          Building the foundation of intelligence.
        </h2>
        <p className="mx-auto mt-5 max-w-xl text-[var(--color-ink-soft)]">
          Register, deposit USDC, and run your first job in minutes — no sales call, no waitlist.
        </p>
        <div className="mt-9 flex flex-wrap justify-center gap-4">
          <Link href="/register">
            <Button size="lg">Create an account</Button>
          </Link>
          <Link href="/docs">
            <Button variant="secondary" size="lg">
              Explore the docs
            </Button>
          </Link>
        </div>
      </div>
    </section>
  );
}

function SectionHeading({
  eyebrow,
  title,
  body,
}: {
  eyebrow: string;
  title: string;
  body: string;
}) {
  return (
    <div className="max-w-2xl">
      <span className="text-xs font-[var(--font-mono)] tracking-[0.25em] text-[var(--color-signal-dim)] uppercase">
        {eyebrow}
      </span>
      <h2 className="mt-3 text-3xl font-[var(--font-display)] font-bold tracking-tight text-[var(--color-ink)] sm:text-4xl">
        {title}
      </h2>
      <p className="mt-4 text-[var(--color-ink-soft)]">{body}</p>
    </div>
  );
}
