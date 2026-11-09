# Docs-Research Eval Case 018: WebAssembly at the Edge

## Research Question
What is the production-readiness of WebAssembly (WASI Preview 2 /
component model) for edge compute platforms in 2026 (Fastly Compute,
Cloudflare Workers, Fermyon Spin, wasmCloud), and what are the
language-support and cold-start trade-offs?

## Required Sources
- official docs of bytecodealliance.org (WASI), wasmcloud.com,
  fermyon.com, fastly.com, developers.cloudflare.com
- at least 3 distinct domains (bytecodealliance.org, fastly.com,
  developers.cloudflare.com, github.com, fermyon.com)
- exclude marketing/blog spam (no platform-pitch landing pages without
  technical content)

## Required Outputs
- /docs/research/wasm-at-edge.md (>=800 words)
- citations array with >=5 entries, each with author/title/url/access_date

## Acceptance
- AC-1: source_citation_count >= 5
- AC-2: word_count >= 800
- AC-3: each citation has author/title/url/access_date
- AC-4: covers WASI Preview 2 / component model status, cold-start
  numbers from at least one operator, and the language-support matrix
  (Rust/Go/JS/Python).

## Out of Scope
No browser-side WASM coverage. No GPU/SIMD intrinsics deep-dive.
