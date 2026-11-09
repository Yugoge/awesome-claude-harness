# Backend-API Eval Case backend-api-007: Fix auth-token rotation race in middleware

## Endpoint or Component
Middleware `requireUserAuth` (Node/Express, `src/middleware/auth.ts`)

## Behavior Required
- Detect tokens issued before the most recent rotation `kid` and reject with HTTP 401 + `{"error":"token_rotated"}`.
- Currently, requests in flight during a rotation race occasionally pass with the old `kid`; this must stop.
- Maintain a 30-second grace window where BOTH old and new `kid` are accepted to avoid mass logouts.
- Cache the active `kid` set in memory; refresh on JWKS endpoint poll every 60 seconds.
- Emit a metric counter `auth.token.rotated_rejected_total` on every rejection.

## Constraints
- Latency budget: p95 under 5 ms (middleware path is hot).
- No new external dependencies; reuse the existing `node-jose` JWKS client.
- Grace window MUST be configurable via `AUTH_ROTATION_GRACE_SECONDS` env var.
- Must NOT log raw token contents; log only `kid`, `iss`, and decision.

## Acceptance
- AC-1: Unit test simulates rotation; pre-rotation token rejected outside grace window.
- AC-2: Test inside the grace window: pre-rotation token accepted, post-rotation also accepted.
- AC-3: `auth.token.rotated_rejected_total` metric increments on rejection.
- AC-4: Server log excerpt shows `kid`, `iss`, `outcome=rejected_token_rotated` (no token).
