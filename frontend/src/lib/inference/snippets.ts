/**
 * Turn a request the playground is about to send into copyable code (Session 5.3).
 *
 * The whole point is that the snippet is the *same request*, not a hand-written imitation of
 * one. Both take the exact object the client passes to `fetch`, so they cannot drift from it
 * by construction — a snippet maintained separately from the caller is a snippet that lies
 * the first time either changes. `snippets.test.ts` pins that equivalence.
 *
 * ⚠️ What they cannot be yet is *runnable*: `/v1/*` does not exist, so the URL these print
 * 404s. Session 5.3's DoD ("the code shown can actually be run") is met only for the "matches
 * the real request" half. It becomes true when the backend lands — with no change here.
 */

export type SnippetLang = "curl" | "typescript" | "python";

export const SNIPPET_LANGS: { id: SnippetLang; label: string }[] = [
  { id: "curl", label: "curl" },
  { id: "typescript", label: "TypeScript" },
  { id: "python", label: "Python" },
];

/** Placeholder for the reader's own key — never interpolate the live session token. */
const KEY = "$GRIDIX_API_KEY";

function pretty(body: unknown): string {
  return JSON.stringify(body, null, 2);
}

export function toCurl(baseUrl: string, path: string, body: unknown): string {
  return [
    `curl ${baseUrl}${path} \\`,
    `  -H "Authorization: Bearer ${KEY}" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '${JSON.stringify(body)}'`,
  ].join("\n");
}

export function toTypeScript(baseUrl: string, path: string, body: unknown): string {
  return [
    `const res = await fetch("${baseUrl}${path}", {`,
    `  method: "POST",`,
    `  headers: {`,
    `    Authorization: \`Bearer \${process.env.GRIDIX_API_KEY}\`,`,
    `    "Content-Type": "application/json",`,
    `  },`,
    `  body: JSON.stringify(${pretty(body).replace(/\n/g, "\n  ")}),`,
    `});`,
  ].join("\n");
}

export function toPython(baseUrl: string, path: string, body: unknown): string {
  const py = pretty(body)
    .replace(/\btrue\b/g, "True")
    .replace(/\bfalse\b/g, "False")
    .replace(/\bnull\b/g, "None");
  return [
    `import os, requests`,
    ``,
    `res = requests.post(`,
    `    "${baseUrl}${path}",`,
    `    headers={"Authorization": f"Bearer {os.environ['GRIDIX_API_KEY']}"},`,
    `    json=${py.replace(/\n/g, "\n    ")},`,
    `)`,
  ].join("\n");
}

export function renderSnippet(
  lang: SnippetLang,
  baseUrl: string,
  path: string,
  body: unknown,
): string {
  switch (lang) {
    case "curl":
      return toCurl(baseUrl, path, body);
    case "typescript":
      return toTypeScript(baseUrl, path, body);
    case "python":
      return toPython(baseUrl, path, body);
  }
}
