# Backend-API Eval Case backend-api-017: Add structured log fields for request tracing

## Endpoint or Component
Logging utility `requestLogger` (Node, `src/utils/logger.ts`)

## Behavior Required
- Every log line emitted during a request lifecycle must include `trace_id`, `span_id`, `user_id?`, `route_pattern`.
- `trace_id` propagated from inbound `traceparent` header (W3C Trace Context); generated if absent.
- Output format: JSON lines, one log entry per line, keys sorted lexicographically.
- Errors include `stack_hash` (first 8 chars of SHA-256 of stack trace) for grouping in log aggregator.
- Sensitive fields (`password`, `token`, `apiKey`) auto-redacted to the literal string `[REDACTED]`.

## Constraints
- Latency budget: per-log-line overhead under 50 microseconds.
- Use `pino` (already a dependency); do NOT add a new logging library.
- Redaction list configurable via `LOG_REDACT_KEYS` env var (comma-separated).
- Logger MUST be safe to call from async contexts (use `AsyncLocalStorage`).

## Acceptance
- AC-1: Unit test confirms every log line has `trace_id`, `span_id`, `route_pattern` keys.
- AC-2: A log call with `{password:"x"}` emits `password:"[REDACTED]"`.
- AC-3: Inbound `traceparent` header value matches `trace_id` in subsequent logs.
- AC-4: Log excerpt for an error includes `stack_hash` matching a 64-bit hex prefix.
