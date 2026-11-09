# Docs-Research Eval Case 007: HTTP/3 vs HTTP/2 in Production

## Research Question
What are the measured production trade-offs of HTTP/3 (QUIC) vs HTTP/2
in 2026, including head-of-line blocking, connection migration, and CDN
deployment readiness?

## Required Sources
- official docs (RFC 9114 for HTTP/3, RFC 9000 for QUIC, RFC 9113 HTTP/2)
- at least 3 distinct domains (rfc-editor.org, ietf.org, cloudflare.com,
  blog.cloudflare.com, web.dev)
- exclude marketing/blog spam (no vendor announcement repackaging)

## Required Outputs
- /docs/research/http3-vs-http2.md (>=800 words)
- citations array with >=5 entries, each with author/title/url/access_date

## Acceptance
- AC-1: source_citation_count >= 5
- AC-2: word_count >= 800
- AC-3: each citation has author/title/url/access_date
- AC-4: includes published latency-improvement numbers from at least one
  CDN operator and notes UDP-blocking middlebox issues.

## Out of Scope
No HTTP/1.1 comparison. No TLS 1.3 deep-dive (covered separately).
