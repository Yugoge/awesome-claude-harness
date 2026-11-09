# Backend-API Eval Case backend-api-005: Add `DELETE /v1/sessions/:id` endpoint with cascade

## Endpoint or Component
HTTP DELETE `/v1/sessions/:id` (Node/Express handler in `src/routes/sessions.ts`)

## Behavior Required
- Soft-deletes the session row by setting `deleted_at = NOW()` (no hard DELETE).
- Cascades a job to the queue: `session.purge.events(sessionId)` for downstream cleanup.
- Returns HTTP 204 on success (no body).
- Returns HTTP 404 if the session does not exist OR is already soft-deleted.
- Idempotent: a second DELETE on a soft-deleted id returns HTTP 404, not HTTP 410.

## Constraints
- Latency budget: p95 under 100 ms (single UPDATE + 1 enqueue).
- Auth: requires `requireUserAuth` AND ownership check OR `admin:sessions:delete` scope.
- Job enqueue MUST happen in the same DB transaction as the soft-delete (outbox pattern).
- No PII (e.g., session content) may appear in the audit log.

## Acceptance
- AC-1: Unit test confirms `deleted_at` populated and a queue row appears in outbox.
- AC-2: Second DELETE returns HTTP 404 within the same test run.
- AC-3: Non-owner without scope receives HTTP 403, not HTTP 404 (info leak avoidance).
- AC-4: `curl -X DELETE /v1/sessions/abc -H "Authorization: Bearer $T"` returns 204.
