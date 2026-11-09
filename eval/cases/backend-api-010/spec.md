# Backend-API Eval Case backend-api-010: Fix CORS middleware wildcard credentials bug

## Endpoint or Component
Middleware `CorsMiddleware` (Node/Express, `src/middleware/cors.ts`)

## Behavior Required
- The middleware currently returns `Access-Control-Allow-Origin: *` together with `Access-Control-Allow-Credentials: true`; this is invalid per spec and must be fixed.
- When credentials are required, echo the request's `Origin` if and only if it is in the allowlist.
- When the request has no `Origin` header (server-to-server), do NOT add any CORS headers.
- Reject requests from disallowed origins with HTTP 403 + `{"error":"origin_not_allowed"}`.
- Maintain backward-compat for the legacy `/public/*` paths that need wildcard but no credentials.

## Constraints
- Latency budget: p95 under 4 ms (header-only middleware).
- Allowlist driven by `CORS_ORIGINS` env var; supports exact match and `*.example.com` wildcards.
- Must run BEFORE auth middleware so preflight rejections do not require a token.
- Logged at INFO level on accept, WARN on reject; never log the full Origin URL beyond hostname.

## Acceptance
- AC-1: Unit test confirms `*` + credentials never co-occur in any response.
- AC-2: Allowed origin with credentials gets back its exact origin in ACAO.
- AC-3: Unknown origin gets HTTP 403 + body `{"error":"origin_not_allowed"}`.
- AC-4: Server log warns once per unknown-origin attempt with hostname only.
