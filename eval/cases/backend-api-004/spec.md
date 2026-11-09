# Backend-API Eval Case backend-api-004: Add `PATCH /v1/users/:id/settings` partial-update endpoint

## Endpoint or Component
HTTP PATCH `/v1/users/:id/settings` (Go/Gin handler in `internal/handlers/settings.go`)

## Behavior Required
- Accepts JSON body containing any subset of: `theme`, `notification_email`, `timezone`.
- Each field validated independently; unknown fields cause HTTP 400 + list of offenders.
- Returns HTTP 200 with the post-update settings object on success.
- Returns HTTP 404 if the user id does not exist.
- Performs partial update; fields absent from the body MUST remain unchanged.

## Constraints
- Latency budget: p95 under 120 ms with Postgres + a single UPDATE statement.
- Authorization: caller must own `:id` OR carry the `admin:settings:write` scope.
- ETag header (`If-Match`) optional; when provided and stale, returns HTTP 412.
- Audit log row written before the response is flushed.

## Acceptance
- AC-1: Unit test PATCH with `{theme:"dark"}` leaves `timezone` and `notification_email` unchanged.
- AC-2: PATCH from a non-owner without scope returns HTTP 403.
- AC-3: PATCH with `{badfield:"x"}` returns HTTP 400 + body `{"unknown":["badfield"]}`.
- AC-4: Audit log line confirms `actor_id`, `target_user_id`, `changed_fields`.
