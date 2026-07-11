---
description: Run a web performance audit via the web-performance-auditor persona
---

`/webperf` targets the Astro / Next frontend specifically. Do not use it for Rust/Python server code, CLIs, or on-chain programs — those have no browser-facing output (use `/review` + `performance-optimization` for compute-unit / server profiling instead).

## Determine the mode

**Deep mode** — activate when any of these is available:
- A Lighthouse JSON report (`npx lighthouse <url> --output json --output-path ./report.json`)
- A PageSpeed Insights JSON response (Lighthouse + CrUX)
- A CrUX API response (`CRUX_API_KEY` / `GOOGLE_API_KEY`)
- A DevTools performance trace
- A live URL plus the `chrome-devtools` MCP server configured in the harness
- The Chrome DevTools MCP CLI run locally (`npx -p chrome-devtools-mcp chrome-devtools lighthouse_audit --output-format=json`)

**Quick mode** — default when none of the above are available. The agent scans source for structural anti-patterns and labels every finding `potential impact`.

## Run the audit

Spawn the `web-performance-auditor` subagent. Pass it explicitly:
- The files, components, or diff under review (note the framework: Astro 5 or Next 15)
- Any artifact paths (Lighthouse/PSI/CrUX JSON, trace) or pasted JSON
- The target URL or page name when known
- Which mode you expect (Quick or Deep)

The subagent returns a scorecard (only populated with sourced values), a ranked findings list, positive observations, and recommendations.

## Output

Return the full audit report to the user. No merge step — this is a single-persona command.
