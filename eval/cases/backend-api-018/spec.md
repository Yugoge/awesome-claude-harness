# Backend-API Eval Case backend-api-018: Add Prometheus histogram for endpoint latency

## Endpoint or Component
Observability module `metrics` (Python/FastAPI, `app/observability/metrics.py`)

## Behavior Required
- Define histogram `http_request_duration_seconds` with buckets `[0.005,0.01,0.025,0.05,0.1,0.25,0.5,1,2.5,5,10]`.
- Labels: `method`, `route_pattern` (templated, never raw URL), `status_code`, `outcome` (success|client_error|server_error).
- Record observation in middleware `MetricsMiddleware` after the handler returns or raises.
- Expose `/metrics` endpoint serving Prometheus text format; protected by `X-Internal-Token` header.
- Cardinality guard: drop label values with > 200 unique entries within a 1-minute window (logged warning).

## Constraints
- Latency budget: middleware adds under 200 microseconds per request.
- Use `prometheus_client` (already in `requirements.txt`); do NOT add OpenTelemetry SDK in this case.
- `/metrics` endpoint MUST be excluded from auth middleware (would otherwise self-recurse).
- Histogram buckets MUST be configurable via `METRICS_BUCKETS_SECONDS` env var (CSV).

## Acceptance
- AC-1: Unit test confirms every request increments the histogram with correct labels.
- AC-2: `curl -H "X-Internal-Token: $T" /metrics` returns 200 + text/plain with the histogram lines.
- AC-3: Cardinality guard log fires on injected high-cardinality `route_pattern` test.
- AC-4: Log excerpt confirms middleware overhead measured under 200 us in benchmark.
