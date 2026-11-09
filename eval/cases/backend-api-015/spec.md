# Backend-API Eval Case backend-api-015: Drop deprecated `legacy_sessions` table

## Endpoint or Component
Postgres migration `2026_05_02_drop_legacy_sessions` (Prisma migration directory)

## Behavior Required
- Confirm zero application code references `legacy_sessions` (grep gate must pass in CI).
- Snapshot the table to S3 (`s3://backups/migrations/legacy_sessions_2026_05_02.parquet`) before dropping.
- Drop the table via `DROP TABLE legacy_sessions CASCADE` only after the snapshot succeeds.
- Migration must be feature-flagged: env var `MIGRATION_DROP_LEGACY_SESSIONS=true` to apply.
- Provide a rollback that restores from the snapshot via `aws s3 cp` + `\copy ... FROM`.

## Constraints
- Latency budget: snapshot stage under 5 minutes for 50M rows.
- Snapshot uses `pg_dump --table=legacy_sessions --format=custom`; never plain SQL dump.
- DROP wrapped in transaction with snapshot verification step.
- All DDL wrapped in idempotent guards (`IF EXISTS`).

## Acceptance
- AC-1: Migration with feature-flag off exits 0 and changes nothing.
- AC-2: Migration with feature-flag on succeeds and `\d legacy_sessions` returns "does not exist".
- AC-3: Snapshot file exists at S3 path with non-zero byte count.
- AC-4: Rollback file restores the table and matches original row count.
