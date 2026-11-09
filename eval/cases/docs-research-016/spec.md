# Docs-Research Eval Case 016: RAG vs Fine-Tune Trade-off (2026)

## Research Question
For a domain-knowledge augmentation problem in 2026, what is the
current best-practice decision framework for RAG vs fine-tuning vs
hybrid (RAFT, DPO-on-RAG-traces), with measurable trade-offs?

## Required Sources
- official papers on arxiv.org plus vendor docs (Anthropic, OpenAI,
  Cohere, LlamaIndex)
- at least 3 distinct domains (arxiv.org, docs.llamaindex.ai,
  anthropic.com, cohere.com, github.com)
- exclude marketing/blog spam (no SaaS pitch posts)

## Required Outputs
- /docs/research/rag-vs-finetune-2026.md (>=800 words)
- citations array with >=5 entries, each with author/title/url/access_date

## Acceptance
- AC-1: source_citation_count >= 5
- AC-2: word_count >= 800
- AC-3: each citation has author/title/url/access_date
- AC-4: explicitly discusses freshness-vs-knowledge depth, eval
  protocols (faithfulness/groundedness), and at least one hybrid
  approach (e.g. RAFT).

## Out of Scope
No vector-DB benchmarking. No closed-product feature comparison.
