# Backend-API Eval Case backend-api-002: Add `POST /v1/users` endpoint with email validation

## Endpoint or Component
HTTP POST `/v1/users` (Node/Express handler in `src/routes/users.ts`)

## Behavior Required
- Accepts JSON body `{ "email": string, "displayName": string, "locale"?: string }`.
- Validates `email` against RFC 5322 regex; rejects malformed input with HTTP 400.
- Returns HTTP 201 with `{ "user_id": string, "created_at": ISO-8601 }` on success.
- Returns HTTP 409 if a user with the same email already exists.
- Persists the user via the existing `userRepository.create()`.

## Constraints
- Latency budget: p95 under 150 ms with the in-memory repo stub.
- Must NOT bypass the existing `requireApiKey` middleware.
- Idempotency-Key header is OPTIONAL but, when present, must dedupe within 24 h.
- Logged user records must omit `email` from any error log.

## Acceptance
- AC-1: Unit test for `POST /v1/users` returns 201 + valid `user_id` for a fresh email.
- AC-2: Duplicate email triggers HTTP 409 and zero new rows in the repo.
- AC-3: Malformed email body returns HTTP 400 with `{"error":"invalid_email"}`.
- AC-4: `curl -H "X-Api-Key: $K" -d '{"email":"a@b","displayName":"A"}' /v1/users` shows 201.
