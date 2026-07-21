/**
 * The `/v1/*` wire types — re-exported from the GENERATED schema, never redeclared.
 *
 * This module replaces the hand-written `types.ts` that stood in while `/v1/*` did not exist.
 * Every name here is an alias into `@/lib/api/schema`, which `pnpm gen:types` derives from
 * the backend's OpenAPI and the `openapi-drift` CI gate keeps honest. Aliasing rather than
 * restating is the whole point: a backend field that changes shape breaks the compiler here
 * instead of surviving as a plausible-looking lie.
 *
 * If something the UI wants is missing from these types, the answer is a backend change and a
 * regenerate — not a widened type. Fields invented here would be exactly the drift the
 * predecessor file was deleted for.
 *
 * UI-only knobs (the settings panels' local state) live in `./params`, deliberately apart:
 * they are view state, not a claim about the wire.
 */

import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];

/** A catalogue model and whether the network is serving it right now. */
export type ModelInfo = Schemas["ModelInfo"];
export type ModelsResponse = Schemas["ModelsResponse"];

export type ChatMessage = Schemas["ChatMessage"];
export type ChatCompletionRequest = Schemas["ChatCompletionRequest"];
export type ChatCompletionResponse = Schemas["ChatCompletionResponse"];

export type ImageGenerationRequest = Schemas["ImageGenerationRequest"];
export type ImageGenerationResponse = Schemas["ImageGenerationResponse"];

// Only the aliases something imports are listed. `modality` is deliberately NOT narrowed to
// a "chat" | "image" union here: it is a plain string on the wire, and a client that hardens
// an open type into a closed one has invented a guarantee the schema does not give. Callers
// compare it directly, so an unrecognised modality lands in neither table rather than being
// mis-sorted into one.
