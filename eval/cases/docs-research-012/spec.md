# Docs-Research Eval Case 012: SQLite WAL Mode

## Research Question
When and how should SQLite Write-Ahead Logging (WAL) be enabled, and
what are the durability, concurrency, and operational implications for
embedded production workloads?

## Required Sources
- official docs of sqlite.org (WAL mode, journal modes, file format)
- at least 3 distinct domains (sqlite.org, fly.io, github.com,
  litestream.io)
- exclude marketing/blog spam (no Top-10 listicles)

## Required Outputs
- /docs/research/sqlite-wal-mode.md (>=800 words)
- citations array with >=5 entries, each with author/title/url/access_date

## Acceptance
- AC-1: source_citation_count >= 5
- AC-2: word_count >= 800
- AC-3: each citation has author/title/url/access_date
- AC-4: covers checkpoint behaviour, busy-timeout interaction with
  multi-writer attempts, and at least one streaming-replication tool
  (Litestream or LiteFS).

## Out of Scope
No comparison with PostgreSQL/DuckDB. No mobile-specific tuning.
