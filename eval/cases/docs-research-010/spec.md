# Docs-Research Eval Case 010: GraphQL vs gRPC Trade-offs

## Research Question
For a service-to-service API in 2026, what are the architectural and
operational trade-offs of GraphQL (federation/persisted queries) vs
gRPC (Connect, gRPC-Web)?

## Required Sources
- official docs of graphql.org and grpc.io (and CNCF Connect docs)
- at least 3 distinct domains (graphql.org, grpc.io, connectrpc.com,
  github.com)
- exclude marketing/blog spam (no SaaS comparison farms)

## Required Outputs
- /docs/research/graphql-vs-grpc.md (>=800 words)
- citations array with >=5 entries, each with author/title/url/access_date

## Acceptance
- AC-1: source_citation_count >= 5
- AC-2: word_count >= 800
- AC-3: each citation has author/title/url/access_date
- AC-4: covers schema evolution, streaming/subscriptions, browser
  reachability, and operational tooling on both sides.

## Out of Scope
No REST/JSON-RPC comparison. No client-library performance microbenchmarks.
