# Backend-API Eval Case backend-api-006: Add `OPTIONS /v1/*` CORS preflight handler

## Endpoint or Component
HTTP OPTIONS catch-all `/v1/*` (Python/FastAPI middleware in `app/middleware/cors_preflight.py`)

## Behavior Required
- Responds to OPTIONS with HTTP 204 and the standard CORS preflight headers.
- Echoes `Access-Control-Request-Headers` into `Access-Control-Allow-Headers`.
- Restricts allowed methods to GET, POST, PUT, PATCH, DELETE, OPTIONS.
- Sets `Access-Control-Max-Age: 600` to enable browser preflight caching.
- Refuses (HTTP 403) when `Origin` is not in the configured allowlist.

## Constraints
- Latency budget: p95 under 30 ms (no DB hit, pure middleware).
- The allowlist is loaded once from `CORS_ORIGINS` env var (comma-separated).
- Must NOT short-circuit non-OPTIONS requests; only OPTIONS is intercepted.
- Must coexist with the existing `RequireAuthMiddleware` without ordering issues.

## Acceptance
- AC-1: `curl -X OPTIONS -H "Origin: https://app.example.com" /v1/foo -i` returns 204 + ACAO header.
- AC-2: OPTIONS with disallowed origin returns 403 (no preflight headers leaked).
- AC-3: Subsequent GET from same origin succeeds (middleware ordering verified).
- AC-4: Unit test confirms `Access-Control-Max-Age: 600` is present on every 204.
