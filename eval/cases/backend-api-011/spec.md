# Backend-API Eval Case backend-api-011: Cache eviction policy for stale session lookups

## Endpoint or Component
Service `SessionCache` (Python, `app/services/session_cache.py`) backed by Redis

## Behavior Required
- Keys evict on TTL (default 600 s) AND on receipt of a `session.invalidated` event from the message bus.
- Currently only TTL eviction works; consumers see stale data for up to 10 minutes after invalidation.
- Event consumer must DELETE the key with a single `DEL` call (not `EXPIRE 0`, which races).
- On Redis unavailability, cache returns `(None, miss)`; never raise to the caller.
- Include `cache_layer="session"` label in every metric emitted from this service.

## Constraints
- Latency budget: cache GET p95 under 5 ms; SET p95 under 10 ms.
- No new Redis client; reuse the existing `redis_pool` injected via DI.
- Event consumer runs in its own asyncio task; must shut down cleanly on SIGTERM.
- TTL configurable via `SESSION_CACHE_TTL_SECONDS`; default 600.

## Acceptance
- AC-1: Unit test publishes `session.invalidated`; subsequent `get()` returns miss within 100 ms.
- AC-2: Redis unreachable test path returns `(None, miss)` without exception.
- AC-3: Metric `session_cache_evictions_total{reason="event"}` increments per invalidation.
- AC-4: Log line confirms `event_id`, `session_id`, `eviction_outcome=ok`.
