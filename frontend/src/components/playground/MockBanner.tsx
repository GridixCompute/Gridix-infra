import { isMockInference } from "@/lib/inference/mock";

/**
 * States plainly that nothing here is real (Sesi 4.2 / 5.4).
 *
 * The build plan allows a marked mock while the inference backend does not exist. "Marked"
 * has to mean visible to whoever is looking at the screen — a comment in the source does not
 * stop a screenshot being mistaken for a working product. Renders nothing once
 * NEXT_PUBLIC_INFERENCE_MOCK=false, so it cannot outlive the mock it warns about.
 *
 * Worded for every surface that shows mocked inference, not just the playground: it also
 * heads the Models page, where there is no reply and nothing streams, and where the thing
 * most likely to be believed is the rate card.
 */
export function MockBanner() {
  if (!isMockInference) return null;
  return (
    // Deliberately not role="status": that is a live region, meant to announce CHANGES. This
    // banner is static and present from first paint, so a live region would not be announced
    // by most screen readers anyway — while stealing the role from the balance warning, which
    // really does appear and disappear. Plain prose is read in document order, before the
    // controls it is warning about.
    <div className="flex items-start gap-3 rounded-[var(--radius-md)] border border-[var(--color-warning)] bg-[#ffab3d14] px-4 py-3">
      <span aria-hidden className="mt-0.5 text-[var(--color-warning)]">
        ▲
      </span>
      <p className="text-sm text-[var(--color-ink-soft)]">
        <strong className="font-semibold text-[var(--color-warning)]">Mock inference.</strong> The
        inference backend doesn&apos;t exist yet — no model runs, no GPU is reached, and nothing is
        charged. The model list, the replies, the images, and every price here are placeholders that
        exist to build the interface against.
      </p>
    </div>
  );
}
