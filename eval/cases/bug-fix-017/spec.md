# Bug-Fix Eval Case 017: Gzip middleware double-encodes already-compressed responses

## Symptom
Browsers report `ERR_CONTENT_DECODING_FAILED` for the
`/api/v1/reports/export?format=csv.gz` endpoint roughly 100% of the time
since the gzip middleware was added. Curl with `--compressed` returns
binary garbage; without `--compressed`, it returns valid gzip bytes — but
the `Content-Encoding: gzip` header is still set.

## Reproduction
1. `curl -i --compressed https://api.example.com/v1/reports/export?format=csv.gz`
2. Response headers include `Content-Encoding: gzip` and binary body fails
   to decode.
3. Without `--compressed`, body is valid gzip but header still asserts
   `Content-Encoding: gzip` — leading curl/browsers to attempt a SECOND
   decode pass.

## Suspected Location
`/workspace/sample-app/src/middleware/gzip.py:33` unconditionally compresses
the response body and sets `Content-Encoding: gzip`. It does not check
whether the response is already compressed (e.g., a `.gz` file already
gzipped by the report exporter at `src/api/reports/export.py:71`).

## Expected Behavior
The middleware skips compression when:
- the response already has `Content-Encoding` set, OR
- the response `Content-Type` is one of the known-compressed types
  (`application/gzip`, `application/zip`, `image/png`, etc.).

## Acceptance
- Add the skip logic guarded by a `SKIP_TYPES` set + a `Content-Encoding`
  header check.
- A pytest test exercises both branches: a plain JSON response gets
  compressed once; a pre-compressed `.gz` response passes through
  untouched (only one `Content-Encoding: gzip` header).
- The reports endpoint also sets the correct `Content-Type:
  application/gzip` so the middleware's type check trips reliably.
