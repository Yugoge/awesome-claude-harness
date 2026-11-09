# Bug-Fix Eval Case 010: SQL injection via unescaped sort parameter

## Symptom
The internal admin search endpoint `/admin/search?sort=<col>` interpolates
the `sort` query parameter directly into a raw SQL string. A security audit
flagged that `sort=name; DROP TABLE users;--` would execute. While the audit
was on staging only, no exploit has been observed in production logs, but
the vulnerability is real and CVSS-scored 9.1 critical.

## Reproduction (in staging only)
1. `curl 'https://staging/admin/search?sort=id;DROP%20TABLE%20fake;--'`
2. Server log shows the raw SQL statement contains the injected DROP clause.
3. (We have rolled back this change in staging — DO NOT reproduce against
   any environment with real data.)

## Suspected Location
`/workspace/sample-app/src/api/admin/search.py:51` builds the query as
`f"SELECT * FROM users ORDER BY {sort} LIMIT 100"` — the `sort` value comes
straight from `request.args` with no whitelist or escaping.

## Expected Behavior
Only a fixed allowlist of column names (`id`, `name`, `created_at`,
`updated_at`) may be used as sort columns. Any other value returns HTTP 400.
The query uses parameterized SQL or a query builder that handles identifier
quoting.

## Acceptance
- Implement an allowlist set and validate `sort` against it before query
  construction.
- Add a pytest test that submits `sort=id;DROP TABLE x;--` and asserts a
  400 response with no DB execution.
- Add the bandit security linter rule `B608` to CI to catch future raw SQL
  string interpolation.
