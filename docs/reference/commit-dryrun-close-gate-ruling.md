# /commit dry-run close-gate relaxation: ruling record

Forensic rationale relocated from `commands/commit.md` (Step 3, close-gate validation). The normative rule lives in that command; this file keeps only the history and the measured caveats.

## Ruling (2026-09-06, section 10.1)

Check 2 of the close-gate (close-report last line is a legal `CLOSE: YES` variant) was made conditional on the `DRYRUN` value parsed in Step 1. Nothing else in the command changed.

Rationale: a `--dry-run` invocation creates no commit, moves no ref, leaves HEAD and worktree bytes unchanged, and leaves the index byte-identical. Gating the preview behind the `CLOSE: YES` approval the preview exists to help earn was a design error; it left the supporting evidence for one close-report unobtainable across five cycles.

## Measured caveat on the ruling's phrasing

The ruling assumed a dry-run never touches the index at all. Measured otherwise: `agents/changelog-analyst.md` saves the index bytes and installs a restoring exit trap (mutate-then-restore), and `scripts/stage-owned-hunks.py` redirects `GIT_INDEX_FILE` to a throwaway index for untracked candidates. What holds is the byte-identical outcome, not a never-touched mechanism.

## Scope at the time

Check 2 only. Checks 1, 3 and 4, the `CLOSE_REPORT` binding, Step 6's QA gate, and every permission, hook and admission gate were unchanged. Check 3 was later demoted to advisory for all invocations (2026-09-26), independently of this ruling. `--force` was not loosened in any form.

## Disclosed widening

Step 5 mints a real single-use 30-minute commit grant per plan entry before any dry-run runs, and the minting is not conditioned on `DRYRUN`, so a task with a failing close-report can cause one to be minted. Four independent backstops bound it: the `--dry-run` stop path and the empty-plan path each revoke it; the grant is single-use and bound to repo + branch + `expected_head`; changelog-analyst's DRYRUN guard forbids consuming it; `pretool-git-privilege-guard.py` blocks agent commits independently. Narrowing it would alter a second gate, which the ruling forbids.

## Why the trigger is read from Step 1 only

The Step 6 planning phase raises `DRYRUN` internally on every invocation. A trigger keyed on "a dry-run is executing" would admit a plain `/commit` with a failing close-report through to a real commit in Step 7.
