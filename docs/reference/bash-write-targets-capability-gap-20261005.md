# bash_write_targets.py capability gap: a fail-open/fail-shut pair from one resolution gap

**Source**: a read-only analysis of `hooks/lib/bash_write_targets.py`'s capability gap, run while investigating why the landed `hooks/tests/test_bash_write_targets_policy.py` (commit `16963b604`) has 5 failures. No code was changed by this record or by the analysis it reports — this document is itself purely additive. The findings below are the analysis session's own report, relayed by the controller; this desk has not independently re-run its measurements.

## 1. An existing fail-open (measured by the analysis session, not inferred)

`hooks/pretool-cp-state-write-guard.py` matches candidate write targets against a fixed set of globs (`_CP_STATE_GLOBS` at line 32, matched via `fnmatch.fnmatchcase` at line 58). When a command places its write target in a shell variable — assigned first, referenced later at the actual sink — `hooks/lib/bash_write_targets.py` currently returns the **unresolved variable-reference literal** (e.g. the token `$OUT`), not the real path. That literal matches none of the configured globs, so the guard admits the write.

Reported comparison: judged against the current (pre-capability) resolver, this shape is admitted (not flagged as a protected write); judged against a version with the missing resolution capability added, the same shape is correctly blocked. The guard is reported bypassable today by this specific shape.

## 2. The same root cause, opposite symptom, on a different consumer

`hooks/pretool-tool-policy.py:111` calls into `hooks/lib/policy_registry.py:268`'s `_check_write_path`. It receives the same unresolved literal, and as a result **denies legitimate writes** too — for role `ba`, both a safe path and a protected path currently come back with the identical denial reason.

This is not "the guard is too loose" or "too strict." It is one resolution gap that reads as *admits what it should block* in one consumer and *blocks what it should admit* in another. The accurate description is "wrong answer," not a directional bias. (Worth flagging explicitly: the controller's initial working assumption going in was "filling the gap only tightens things" — the analysis disproved that.)

## 3. The capability gap itself

Master's `hooks/lib/bash_write_targets.py` (1187 lines) lacks two functions: one that projects a variable assignment's right-hand side into a literal path, and one that resolves that variable backward from its byte position at the sink. The analysis session reports confirming this via four independent lookup approaches plus an AST walk, cross-checked against a positive control. Master does not solve the same problem a different way — its only path-resolution function performs plain-text `$HOME`/`~` substitution, unrelated to variable assignment.

## 4. Why the fix is not landed tonight (recorded so it isn't mistaken later for an oversight)

- Filling the gap makes a **security hook** start spawning a shell subprocess, fed by model-produced input. The analysis session reports measuring 14 adversarial inputs, all refused by the syntax gate before any subprocess spawn, zero canaries produced — but this is a design-level change that needs an explicit human sign-off, not something to wave through on green tests alone.
- The analysis session's broad regression sweep (74 files) was aborted at a 10-minute timeout, so "no broad regression" is **not established**; the analysis session itself flagged this as the weakest link in its own judgment.
- The narrow evidence is good (three test suites pinning this library reported going from 522 to 527 passing, 42 doctests passing, public-signature pins still holding) but does not substitute for the first two points above.

## 5. A finding about what a passing test actually proves

Of the 9 matrix cases in the landed `hooks/tests/test_bash_write_targets_policy.py` that currently "pass," the analysis reports **8 pass vacuously**: master returns the unresolved literal for every variable shape, and those 8 rows happen to expect exactly that literal as their answer (they were written as fail-closed rows — use-before-assign, double assignment, subshell, command substitution, indirect expansion, no assignment at all). So this file, as it stands, provides almost no evidence that master's fail-closed behavior is deliberate design — it looks more like an accident that happens to be correct. Only once the capability gap above is filled would those 8 rows actually exercise the rejection branch and start carrying evidence.

Worth calling out on its own: **a passing test does not establish what it is testing.**

## Disposition

No code changed by this record. Cross-referenced in `docs/reference/harness-issues-backlog.md` (security-relevant entry, following that file's existing convention and attribution marks for such findings).
