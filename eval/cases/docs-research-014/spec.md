# Docs-Research Eval Case 014: LLM Context-Window Scaling

## Research Question
What are the published techniques for scaling LLM context windows beyond
1M tokens (RoPE/YaRN/ALiBi/landmark attention/ring attention) and what
are their measured quality and cost trade-offs in 2026?

## Required Sources
- official papers on arxiv.org and vendor research blogs (Anthropic,
  Google DeepMind, Meta AI Research)
- at least 3 distinct domains (arxiv.org, anthropic.com,
  research.google, ai.meta.com)
- exclude marketing/blog spam (no Twitter screenshots, no
  AI-influencer recap posts)

## Required Outputs
- /docs/research/llm-context-window-scaling.md (>=800 words)
- citations array with >=5 entries, each with author/title/url/access_date

## Acceptance
- AC-1: source_citation_count >= 5
- AC-2: word_count >= 800
- AC-3: each citation has author/title/url/access_date
- AC-4: covers at least three positional-encoding/attention techniques
  AND a "needle in a haystack" or RULER-style evaluation result.

## Out of Scope
No fine-tuning specifics. No comparison of closed-model API pricing.
