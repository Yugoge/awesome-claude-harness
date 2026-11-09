# Backend-API Eval Case backend-api-003: Add `GET /v1/search` full-text endpoint

## Endpoint or Component
HTTP GET `/v1/search` (Python/FastAPI router in `app/api/search.py`)

## Behavior Required
- Accepts `?q=<term>&limit=<int>&cursor=<opaque>` query parameters.
- Default `limit=20`, hard cap at 100; `limit > 100` returns HTTP 400.
- Performs case-insensitive prefix match against `documents.title` and `documents.body`.
- Returns `{ "results": [...], "next_cursor": string | null }` paginated response.
- Empty `q` returns HTTP 400 with explanatory error code `q_required`.

## Constraints
- Latency budget: p95 under 250 ms for catalogs of 100k rows (Postgres + GIN index).
- Must reuse the existing `SearchService` dependency (no new DB clients).
- Cursor must be opaque (base64 of `(score, id)`) and stable across paginated calls.
- Total response body capped at 1 MiB; truncate with `truncated:true` field if exceeded.

## Acceptance
- AC-1: Unit test confirms pagination cursor round-trips for >limit results.
- AC-2: `curl '/v1/search?q=' -i` returns HTTP 400 + body `{"error":"q_required"}`.
- AC-3: `curl '/v1/search?q=foo&limit=200'` returns HTTP 400 (cap enforced).
- AC-4: Log line includes `request_id`, `q_length`, `result_count` (no raw `q`).
