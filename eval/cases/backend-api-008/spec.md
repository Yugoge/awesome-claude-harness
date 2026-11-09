# Backend-API Eval Case backend-api-008: Fix rate-limit middleware off-by-one bucket boundary

## Endpoint or Component
Middleware `RateLimit` (Go/Gin, `internal/middleware/ratelimit.go`)

## Behavior Required
- Sliding-window rate limiter incorrectly allows N+1 requests at exact bucket rollover; must enforce N strictly.
- Returns HTTP 429 + `Retry-After` header (seconds until next bucket starts) on overflow.
- Buckets keyed by `(client_ip, route_pattern)`; per-route limits configured in `ratelimit.yaml`.
- On Redis failure, fall back to in-process token bucket (fail-open is forbidden).
- Emit `ratelimit.rejected_total{route}` metric on every 429.

## Constraints
- Latency budget: p95 under 8 ms with Redis hit, under 3 ms with in-process fallback.
- Must NOT count OPTIONS preflight requests against the limit.
- Clock source MUST be monotonic (`time.Now().UnixNano()`), not wallclock.
- Configuration reload via SIGHUP; no restart needed.

## Acceptance
- AC-1: Unit test asserts exactly N requests pass and the (N+1)th returns 429.
- AC-2: `Retry-After` header present and within (0, bucket_seconds] range.
- AC-3: Redis-down test path falls back without HTTP 5xx leakage.
- AC-4: Log excerpt confirms `client_ip`, `route`, `bucket_count`, `decision=rejected`.
