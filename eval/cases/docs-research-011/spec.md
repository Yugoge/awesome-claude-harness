# Docs-Research Eval Case 011: Postgres Logical Replication

## Research Question
What is the production reference for Postgres logical replication
(>=v15) including publication filters, row filtering, conflict handling,
and DDL-replication gaps?

## Required Sources
- official docs of postgresql.org (logical replication chapter, release
  notes 15-17)
- at least 3 distinct domains (postgresql.org, wiki.postgresql.org,
  github.com, citusdata.com)
- exclude marketing/blog spam (no managed-DB sales decks)

## Required Outputs
- /docs/research/postgres-logical-replication.md (>=800 words)
- citations array with >=5 entries, each with author/title/url/access_date

## Acceptance
- AC-1: source_citation_count >= 5
- AC-2: word_count >= 800
- AC-3: each citation has author/title/url/access_date
- AC-4: covers row/column filters, REPLICA IDENTITY requirements, the
  DDL-replication limitation, and recommended monitoring queries.

## Out of Scope
No physical-replication or pg_basebackup coverage. No vendor pricing.
