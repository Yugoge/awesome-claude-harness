# Backend-API Eval Case backend-api-016: Rename FK `sessions.owner_id` to `sessions.user_id`

## Endpoint or Component
Postgres migration `2026_05_03_rename_sessions_owner_id` (Prisma migration directory)

## Behavior Required
- Rename column `sessions.owner_id` to `sessions.user_id` to match new naming convention.
- Update the FK constraint name from `sessions_owner_id_fkey` to `sessions_user_id_fkey`.
- Drop the old index `idx_sessions_owner_id` and create a new `idx_sessions_user_id`.
- Update the Prisma schema (`schema.prisma`) field name; regenerate the client.
- Provide a forward + rollback migration; rollback must restore the original name and constraint.

## Constraints
- Latency budget: total downtime under 5 s on a 20M-row table (rename is metadata-only).
- DDL wrapped in a single transaction so a partial failure leaves the schema unchanged.
- Application code that referenced `owner_id` must be updated in the same release branch.
- Rollback file must be tested against a snapshot before production apply.

## Acceptance
- AC-1: Apply migration; `\d sessions` shows `user_id` column and `sessions_user_id_fkey` constraint.
- AC-2: Old index `idx_sessions_owner_id` no longer exists; new index appears.
- AC-3: Generated Prisma client compiles and exposes `session.userId` field.
- AC-4: Rollback restores the table to bytewise-identical schema (verified by `pg_dump --schema-only`).
