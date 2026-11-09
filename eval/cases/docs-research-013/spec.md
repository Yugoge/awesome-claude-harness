# Docs-Research Eval Case 013: ClickHouse vs Druid

## Research Question
For interactive analytics on multi-billion-row event streams in 2026,
how do ClickHouse and Apache Druid compare on ingestion model, query
latency, operational footprint, and cost-per-TB?

## Required Sources
- official docs of clickhouse.com and druid.apache.org
- at least 3 distinct domains (clickhouse.com, druid.apache.org,
  github.com, blog by maintainers)
- exclude marketing/blog spam (no vendor-funded benchmark posts without
  reproducible methodology)

## Required Outputs
- /docs/research/clickhouse-vs-druid.md (>=800 words)
- citations array with >=5 entries, each with author/title/url/access_date

## Acceptance
- AC-1: source_citation_count >= 5
- AC-2: word_count >= 800
- AC-3: each citation has author/title/url/access_date
- AC-4: covers segment/shard architecture, real-time ingestion paths,
  operator/Helm story, and at least one published benchmark with
  caveats.

## Out of Scope
No Pinot, BigQuery, or Snowflake comparison. No managed-cloud pricing.
