# Backend-API Eval Case backend-api-012: Queue retry exponential backoff with jitter

## Endpoint or Component
Service `JobRetryScheduler` (Go, `internal/queue/retry.go`)

## Behavior Required
- Replace the existing fixed-delay retry (5 s) with exponential backoff base 2 from 1 s capped at 5 minutes.
- Add full jitter per AWS Architecture Blog formula: `delay = random(0, min(cap, base * 2^n))`.
- Max 8 attempts; on overflow, route the job to the dead-letter queue with reason `max_retries_exceeded`.
- Persist `attempt_count` and `next_attempt_at` per job in the `jobs.retries` JSONB column.
- Emit metric `queue_retry_attempts_total{outcome="scheduled|deadletter"}`.

## Constraints
- Latency budget: scheduling decision under 2 ms (no DB hit, just compute).
- Random source: crypto/rand, not math/rand (deterministic-test mode allowed via interface).
- DLQ writes use the same outbox pattern as the rest of the queue layer.
- Backoff cap MUST be configurable via `QUEUE_RETRY_CAP_SECONDS` env var.

## Acceptance
- AC-1: Unit test with seeded RNG asserts delays follow `random(0, base*2^n)` distribution.
- AC-2: After 8 failed attempts, job lands in DLQ with `reason=max_retries_exceeded`.
- AC-3: `queue_retry_attempts_total` increments with the right outcome label.
- AC-4: Log excerpt shows `job_id`, `attempt`, `delay_ms`, `next_attempt_at`.
