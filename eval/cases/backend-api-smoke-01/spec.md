# backend-api-smoke-01

## Title
Add `POST /v1/sessions/:id/archive` endpoint with auth middleware

## Context
The happy-server currently exposes session lifecycle endpoints under
`/v1/sessions/...` (create, reactivate, end). Operators have asked for a
soft-archive endpoint that marks a session as `archived=true` without
deleting any data, so it disappears from the default `/v1/sessions/list`
response but remains available under `/v1/sessions/list?archived=true`.

## Required Behavior
- New route `POST /v1/sessions/:id/archive` (no body required).
- Returns `200 {"archived": true, "session_id": "..."}` on success.
- Returns `404` if the session id does not exist.
- Requires the existing `requireUserAuth` middleware.
- Default `/v1/sessions/list` filters out archived sessions; passing
  `?archived=true` includes them.

## Verification
- Unit tests against the route handler.
- A `curl` transcript hitting the new endpoint with a valid token.
- Server log excerpt confirming the auth middleware fired.

## Out of Scope
No UI changes. No DB migration beyond the boolean column already present
on the `sessions` table.
