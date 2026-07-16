import { isMockInference } from "@/lib/inference/mock";

/**
 * States plainly that nothing here is real (Sesi 4.2).
 *
 * The build plan allows a marked mock while the inference backend does not exist. "Marked"
 * has to mean visible to whoever is looking at the screen — a comment in the source does not
 * stop a screenshot being mistaken for a working product. Renders nothing once
 * NEXT_PUBLIC_INFERENCE_MOCK=false, so it cannot outlive the mock it warns about.
 */
export function MockBanner() {
  if (!isMockInference) return null;
  return (
    <div
      role="status"
      className="flex items-start gap-3 rounded-[var(--radius-md)] border border-[var(--color-warning)] bg-[#ffab3d14] px-4 py-3"
    >
      <span aria-hidden className="mt-0.5 text-[var(--color-warning)]">
        ▲
      </span>
      <p className="text-sm text-[var(--color-ink-soft)]">
        <strong className="font-semibold text-[var(--color-warning)]">Mock playground.</strong> The
        inference backend doesn&apos;t exist yet — no model runs, no GPU is reached, and nothing is
        charged. Replies are canned text streamed to build the interface. Token counts and costs are
        arithmetic on a placeholder rate card.
      </p>
    </div>
  );
}
