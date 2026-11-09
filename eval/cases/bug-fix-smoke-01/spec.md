# bug-fix-smoke-01

## Title
Fix off-by-one in array indexing in `scripts/foo.py`

## Symptom
The function `compute_window_sum(values, window)` in `scripts/foo.py:42` returns
the wrong total when the input list length is exactly equal to `window`.
Concretely, calling `compute_window_sum([1, 2, 3], 3)` returns `5` instead of
the expected `6`.

## Reproduction
1. Open a Python REPL in the repo root.
2. `from scripts.foo import compute_window_sum`
3. Run `compute_window_sum([1, 2, 3], 3)` — observe `5`.

## Expected Behavior
For an input list of length `N` and window size `W` where `N == W`, the
function should sum every element exactly once and return `sum(values)`. In
the example, the expected return is `6`.

## Hypothesized Root Cause
The loop boundary at `scripts/foo.py:48` uses `range(len(values) - window)`
instead of `range(len(values) - window + 1)`, dropping the last valid window.

## Acceptance
A new unit test in `tests/test_foo.py` covering the equal-length case must
pass after the fix.
