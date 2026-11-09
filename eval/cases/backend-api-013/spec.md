# Backend-API Eval Case backend-api-013: Webhook signature verification (HMAC-SHA256)

## Endpoint or Component
Service `WebhookVerifier` (Node, `src/services/webhookVerifier.ts`)

## Behavior Required
- Verify incoming webhook payloads via `X-Signature-256: sha256=<hex>` header using HMAC-SHA256.
- Constant-time comparison via `crypto.timingSafeEqual`; never use `===` on the digests.
- Reject if header missing, malformed, or mismatched: HTTP 401 + `{"error":"signature_invalid"}`.
- Support secret rotation: accept either `current` or `previous` secret for a 24 h window.
- Log a structured warning on mismatch including `delivery_id` and `attempted_secret_label`.

## Constraints
- Latency budget: verification under 1 ms for payloads up to 64 KiB.
- No external libraries beyond Node's built-in `crypto` module.
- Secret loaded from env vars `WEBHOOK_SECRET_CURRENT` / `WEBHOOK_SECRET_PREVIOUS`.
- Body must be read RAW (not parsed JSON) before HMAC computation.

## Acceptance
- AC-1: Unit test with valid signature returns next() without error.
- AC-2: Tampered body fails verification, HTTP 401 returned.
- AC-3: Rotated-secret test (signed with `previous`) succeeds within 24 h window.
- AC-4: Log warns on mismatch with `delivery_id` present and full body absent.
