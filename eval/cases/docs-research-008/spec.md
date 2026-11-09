# Docs-Research Eval Case 008: WebTransport Protocol Survey

## Research Question
What is the production maturity of WebTransport (over QUIC) in 2026,
including browser support, server libraries, and use-cases that beat
WebSockets?

## Required Sources
- official docs of W3C / IETF (WebTransport spec, draft RFC)
- at least 3 distinct domains (w3.org, ietf.org, web.dev, github.com)
- exclude marketing/blog spam (no chatbot-generated tutorials)

## Required Outputs
- /docs/research/webtransport.md (>=800 words)
- citations array with >=5 entries, each with author/title/url/access_date

## Acceptance
- AC-1: source_citation_count >= 5
- AC-2: word_count >= 800
- AC-3: each citation has author/title/url/access_date
- AC-4: covers datagram vs reliable-stream APIs, current browser support
  matrix, and at least one production case study (cloud gaming or
  low-latency analytics).

## Out of Scope
No WebRTC comparison. No QUIC handshake internals.
