# Bug-Fix Eval Case 009: Catastrophic regex backtracking on email validator

## Symptom
The signup endpoint hangs the worker process for >30 seconds when submitted
with certain pathological email-shaped strings, e.g. an `@` followed by 30
`a`s and no TLD. Production has seen sustained CPU saturation and triggered
the request-timeout guard 14 times in the last 24 hours.

## Reproduction
1. `curl -X POST /api/v1/signup -d 'email=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'`
2. Worker pegs one CPU core at 100% for >30s before the timeout fires.
3. py-spy dump shows the hot frame is the regex compile/match loop in
   `email_validator.py`.

## Suspected Location
`/workspace/sample-app/src/validators/email_validator.py:14` uses the
pattern `^([a-zA-Z0-9_.+-]+)+@([a-zA-Z0-9-]+)+\.([a-zA-Z]+)$`. The nested
quantifiers `(...+)+` cause exponential backtracking on inputs that fail to
match.

## Expected Behavior
Validation runs in O(N) on the input length; even a 1024-char pathological
input completes in <50ms. Invalid emails return HTTP 400 quickly.

## Acceptance
- Replace the regex with a non-backtracking version (no nested quantifiers),
  e.g. `^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]+$`.
- A pytest benchmark asserts validating a 1024-char hostile input completes
  in <100ms.
- Consider switching to the `email-validator` library which uses a
  tokenizer; document the choice in the file header.
