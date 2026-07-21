/**
 * UI-only knobs the settings panels drive. NOT wire types — see `./contract` for those.
 *
 * These exist because the panels need local state with UI-friendly names (`maxTokens`) and a
 * "let the node choose" sentinel (`seed: null`) that the request encodes as an absent field.
 * They are mapped onto a real request in the panels' `buildRequest`, so every field here has
 * to correspond to something the backend actually accepts.
 *
 * Nothing may be added here that `/v1/*` does not take. The deleted `types.ts` carried
 * `top_p`, image `size` and image `steps` — all three were invented, none exist in
 * `ChatCompletionRequest` or `ImageGenerationRequest`, and the playground offered them as
 * working controls. A knob the API ignores is a lie the UI tells with a slider.
 */

/** Chat knobs. Maps to `temperature`, `max_tokens`, `seed`. */
export type ChatParams = {
  temperature: number;
  maxTokens: number;
  /** null = omit `seed` and let the node choose; a number pins determinism. */
  seed: number | null;
};

/**
 * Image knobs. Maps to `seed` only.
 *
 * `ImageGenerationRequest` also carries `n` (1–8), but the panel generates one image at a
 * time and prices it as one, so `n` is pinned to 1 at the call site rather than exposed as a
 * control whose cost implications the gate does not yet model.
 */
export type ImageParams = {
  /** null = omit `seed` and let the node choose. */
  seed: number | null;
};
