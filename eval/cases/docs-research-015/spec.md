# Docs-Research Eval Case 015: Prompt-Cache ROI

## Research Function
What is the measurable ROI of prompt caching for LLM-backed
applications (Anthropic, OpenAI, Google) in 2026, including hit-rate
patterns, TTL design, and cost-amortization math?

## Research Question
Same as above section.

## Required Sources
- official docs of Anthropic, OpenAI, Google AI on prompt caching
- at least 3 distinct domains (anthropic.com, platform.openai.com,
  ai.google.dev, github.com)
- exclude marketing/blog spam (no vendor-comparison clickbait)

## Required Outputs
- /docs/research/prompt-cache-roi.md (>=800 words)
- citations array with >=5 entries, each with author/title/url/access_date

## Acceptance
- AC-1: source_citation_count >= 5
- AC-2: word_count >= 800
- AC-3: each citation has author/title/url/access_date
- AC-4: includes a worked cost-savings example (input tokens, hit rate,
  per-token list price) and discusses TTL implications for shared
  systems.

## Out of Scope
No KV-cache implementation internals. No self-hosted-model coverage.
