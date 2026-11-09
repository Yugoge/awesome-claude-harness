# Backend-API Eval Case backend-api-014: Add `users.archived_at` column with online backfill

## Endpoint or Component
Postgres migration `2026_05_01_add_users_archived_at` (Prisma migration directory)

## Behavior Required
- Add `archived_at TIMESTAMPTZ NULL` column to `users` table without taking an exclusive lock.
- Backfill existing rows in batches of 1000 using `UPDATE users SET archived_at = NULL WHERE archived_at IS NULL`.
- Add a partial index `idx_users_archived_at_not_null ON users (archived_at) WHERE archived_at IS NOT NULL`.
- Migration must be idempotent: re-running it on a table that already has the column is a no-op.
- Document a rollback file that drops both the index and the column safely.

## Constraints
- Latency budget: total migration window under 30 s on a 5M-row table (target).
- MUST NOT block writes for more than 100 ms at any point (use `lock_timeout=100ms`).
- Use `CREATE INDEX CONCURRENTLY` for the partial index.
- All DDL wrapped in proper Prisma migration files (forward + rollback).

## Acceptance
- AC-1: Apply on a fresh DB completes without error; `\d users` shows the new column + index.
- AC-2: Re-applying the migration on an already-migrated DB exits 0 with no changes.
- AC-3: `EXPLAIN` of `WHERE archived_at IS NOT NULL` query uses the partial index.
- AC-4: Rollback file successfully drops the index then the column in correct order.
