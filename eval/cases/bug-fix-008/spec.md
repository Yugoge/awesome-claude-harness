# Bug-Fix Eval Case 008: Race condition in cache write loses updates under load

## Symptom
The product-price cache occasionally serves prices from two updates ago. The
issue only reproduces under concurrent load (>50 RPS) and shows up as ~0.3%
of `/api/v1/products/{id}` responses being demonstrably stale (verified
against the source-of-truth DB row written milliseconds earlier).

## Reproduction
1. Run `locust -f bench/price_writes.py` with 100 concurrent users for 60s.
2. The bench script writes monotonic prices and reads back immediately.
3. ~3 reads per 1000 see a price strictly less than what was written.

## Suspected Location
`/workspace/sample-app/src/cache/price_cache.py:62` performs
`current = redis.get(key); new = max(current, incoming); redis.set(key, new)`
as three separate operations with no transaction or lock — two concurrent
writes can both read the same `current`, both compute their own `new`, and
the second `set` overwrites the first.

## Expected Behavior
Concurrent writers must produce a final cached value equal to the maximum
incoming value, with no lost updates. Reads after a successful write must
never observe a value lower than what was written.

## Acceptance
- Replace the read-modify-write with a Redis Lua script that does the
  compare-and-swap atomically, OR use `WATCH`/`MULTI`/`EXEC`.
- A pytest test launches 50 threads writing values 1..50 to the same key and
  asserts the final cached value is 50.
- Add a Prometheus counter `cache_lost_update_attempts_total` for any future
  observability.
