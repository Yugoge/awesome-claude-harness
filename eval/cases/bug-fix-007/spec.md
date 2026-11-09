# Bug-Fix Eval Case 007: Off-by-one in pagination skips one result per page

## Symptom
The `/api/v1/orders?page=N&size=20` endpoint returns 20 records on page 1 but
silently skips one record between every page boundary. After paging through
the dataset, the client has 19 fewer rows than the reported `total_count`.

## Reproduction
1. Seed the orders table with exactly 100 rows (`o_001` through `o_100`).
2. `GET /api/v1/orders?page=1&size=20` returns o_001..o_020.
3. `GET /api/v1/orders?page=2&size=20` returns o_022..o_041 — note o_021
   is missing.
4. After paging through page=5, only 81 unique IDs collected; `total_count`
   in the response correctly reports 100.

## Suspected Location
`/workspace/sample-app/src/api/orders/list.py:78` builds the offset as
`offset = page * size` instead of `offset = (page - 1) * size`. On page 2,
offset becomes 40 instead of 20, but the limit caps at 20 — so rows 21-40 of
the first page are correct, then page 2 jumps past row 21 entirely.

## Expected Behavior
Concatenating all pages yields exactly the full result set in order, with no
gaps and no duplicates. `total_count` matches the count of distinct rows
returned across all pages.

## Acceptance
- A pytest fixture seeds 100 rows, requests pages 1-5, and asserts the
  union equals all 100 IDs.
- The offset formula is corrected to `(page - 1) * size`.
- Add a defensive check that rejects `page < 1` with HTTP 400 to prevent
  underflow from masking the bug.
