# Bug-Fix Eval Case 011: Datetime tz-aware vs naive comparison raises TypeError

## Symptom
The nightly subscription-renewal job crashes intermittently with
`TypeError: can't compare offset-naive and offset-aware datetimes` when
comparing a subscription's `next_renewal_at` against `datetime.utcnow()`.
Roughly 11% of subscriptions trigger the crash; the rest are processed.

## Reproduction
1. Run `python jobs/renew_subscriptions.py` against the staging DB.
2. The script crashes after processing a subset of subs.
3. The failing rows all have `next_renewal_at` stored with a timezone
   (`tzinfo=UTC`) while the script uses `datetime.utcnow()` (naive).

## Suspected Location
`/workspace/sample-app/src/jobs/renew_subscriptions.py:88` does
`if sub.next_renewal_at <= datetime.utcnow(): renew(sub)`. The DB column is
`TIMESTAMP WITH TIME ZONE` so SQLAlchemy returns aware datetimes, but
`datetime.utcnow()` returns a naive datetime.

## Expected Behavior
All datetime comparisons in the job use timezone-aware UTC values. No
TypeError is raised regardless of which subscription rows are processed.

## Acceptance
- Replace `datetime.utcnow()` with `datetime.now(timezone.utc)` in the
  job (and grep the rest of the codebase for the same anti-pattern).
- A pytest test inserts a subscription with a tz-aware `next_renewal_at`
  and asserts the job processes it without raising.
- Add a `mypy --strict` rule (or a custom flake8 plugin) that flags
  `datetime.utcnow()` usage going forward.
