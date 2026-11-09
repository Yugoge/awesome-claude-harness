# Backend-API Eval Case backend-api-009: Fix gzip middleware double-compression bug

## Endpoint or Component
Middleware `gzipResponse` (Python/FastAPI, `app/middleware/gzip.py`)

## Behavior Required
- When the upstream handler already returns a `Content-Encoding: gzip` body, the middleware currently re-compresses it; must skip in that case.
- When body is uncompressed and `Accept-Encoding: gzip` is honored, compress streams >= 1 KiB.
- Add `Vary: Accept-Encoding` to every response that goes through the middleware.
- Avoid compressing `image/*`, `video/*`, `application/zip` content types.
- Set the `Content-Length` header AFTER compression (do not pre-trust upstream length).

## Constraints
- Latency budget: p95 under 12 ms additional overhead vs uncompressed path.
- Compression level fixed at 6 (good speed/ratio tradeoff).
- Must NOT buffer the entire response in memory for streams larger than 4 MiB; switch to chunked.
- Reentrant: must work behind a load balancer that may have already added `Vary`.

## Acceptance
- AC-1: Unit test for already-gzipped upstream body: middleware leaves body bytewise identical.
- AC-2: `curl --compressed -i /v1/data` returns `Content-Encoding: gzip` exactly once.
- AC-3: PNG response NOT recompressed (header check).
- AC-4: Log line shows `compressed=false reason=already_encoded` when middleware skips.
