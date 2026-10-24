This is the full record of the P7b pull request; the PR description on GitHub is its shortened form.

Owner steps: none.

# P7b: a live home lands P7 by itself

## Summary

A harness home that ran pre-P7 code and receives master through any pull path now reaches, at the
next turn end of any of its sessions, the state P7's manual migration would have produced: nothing
to type, no session to stop, nothing that blocks a Stop. `hooks/auto-commit.sh` (registered by a
pre-P7 `settings.json` and by the clean form alike) runs `scripts/install/land`, which:

- leaves a landed home alone: three git calls (the third is `git diff-files` on `settings.json`),
  one `cmp` per hook init step 5 installs and one builtin read of each `/proc/<pid>/cmdline` (a
  fourth git call while a stash entry is kept, and then one `git diff` per unmerged index or
  `CLAUDE.md`; one `stat` and one `getconf` while a git-fswatch daemon runs; one `git diff` of
  `settings.json` through the filter per write of that file); measured +16.7 to +25.8
  ms per Stop on 921b5128, whose landed fast path this head runs unchanged (limit 50; load
  average 0.39 0.60 0.73;
  +18.6 to +22.6 on 96bcb8f2, +15.7 to +17.9 on 26a7ea7a), and on 26a7ea7a, whose landed fast path
  this head does not change, +15.8 to +21.1 ms with a kept
  stash entry and +20.5 to +27.1 ms with a current daemon running on the home;
- on a landed home whose `settings.json` a CLI write of a key the clean form leaves out (`model`,
  `theme`, ...) left stat-dirty, re-records its index stat the way render does, so that /pull and
  fswatch pull again from the next Stop on (review N1: before, they refused or skipped every pull);
  a write is told by `settings.json`'s mtime against an empty marker file the landing keeps, a
  departure from P7b.md's no-marker rule decided by review NF-1's experiment (no variant without a
  file of its own kept N1 fixed within the +50 ms budget; "Decisions applied");
- on an upgraded home (its HEAD reflog, as an entry's new or old value, or `ORIG_HEAD` holds a
  revision from before the settings filter, and the reflog does not start with a clone of a revision
  that declares it), one session at a time: renames aside the legacy auto-push post-commit hooks
  (git-lfs's own post-commit takes the place of a combined LFS hook; one that its repository tracks
  is left and counted) and restarts stale git-fswatch daemons (in this home and in the
  repositories under `$HOME`; only the home's own daemon in the middle of its git work makes the
  landing wait, before any setting is written), undoes what a conflicted stash pop of the pull left
  in the index, migrates the previous personal settings into a new overlay through the one producer
  `render-settings migrate` (never `GIT_AUTO_PUSH` "1"), seeds an absent or empty
  `private-literals.txt` (leaving out a value that HEAD's tracked files hold in 100 or more lines,
  and a path under the harness home that rev's hook commands name), takes `settings.json` from HEAD
  for as long as no render has run, then runs init steps 3-5 (`scripts/bootstrap --steps 3,4,5`); a
  whole Stop that lands a home measured 1.60 to 1.78 s, a landing with 3500 repositories under `$HOME`
  8.22 s, and one with three daemons that need the KILL 9.4 s (on round 2's head); its bound by
  construction, about 13 s with the loop over the repositories under `$HOME` included, is under
  "Test evidence";
- waits and says so when a rebase, merge, squash merge, cherry-pick or revert is stopped in the home
  (S4), and changes nothing;
- on a landed home, takes upstream's side for `settings.json` (naming by key path the live entries
  upstream's side lacks, which the kept stash entry still holds) and for index / `CLAUDE.md` files
  whose only local change is doc-sync's date line, when a later pull's stash pop conflicts on them
  (R2's doc-sync exception, so P8's, P9's and P10's index deletions do not stop every later pull),
  says so while a git lock refuses that repair, naming each path it refused ("settings.json still
  conflicted: git refused its repair, tried again at the next turn end", "CLAUDE.md, settings.json
  still conflicted: ...", a control or line-break character in a name as `?`, reviews NV1-2-1
  and NVF-1), logged as
  `result=repair-refused` (reviews V1-1, NV-1), says so when the repair run fails outright ("the
  settings repair failed (see logs/landing.log); it runs again at the next turn end",
  `result=repair-failed`, reviews NV1-2-2 and NVF-2), runs nothing for a conflict that is the owner's own, and restarts a stale daemon
  (one the landing left running, or one older than a later pull) once it can.

Three defects of the pull paths themselves are fixed as well, two routed to this phase by the
review of PR #6 and one by review NF-2: /pull (`hooks/pull.sh`) and fswatch's `safe_pull` pop only a
stash entry their own push made (with untracked files alone they popped an older entry, on a landed
home the one a conflicted pop kept, or failed with "No stash entries found"), and `safe_pull` takes
a failed stash pop as failed (it logged "Stashed changes restored" and returned 0).

Sessions that started before the landing read the push switch and the overlay's guard settings
from the rendered `settings.json` (R7). The session sees one plain line per Stop;
`logs/landing.log` records counts and key names, never a value.

Phases merged when measured: P0, P0b, P7 and P1 (`origin/master` = d625284, "Merge pull request #5";
`git log --oneline f8c18c2..origin/master`: 13 P1 commits and that merge; `origin/master` re-read
from GitHub on 2026-10-23: still d625284). P8 (PR #6, head 0d266922) is not merged and merges after
this PR; a trial merge with it is reported at the end. The branch is based on d625284. P1's
coordinator relays a passing phase's last-line `systemMessage` for any phase
(`hooks/stop-workflow-coordinator.py` `_run_phase`, `main`), so the landing notice reaches the session
through it: every notice quoted below was relayed by P1's coordinator.

## Type of change

- [x] Bug fix
- [x] New feature / capability
- [x] Documentation
- [x] Hook / script / config change
- [ ] Other (describe):

## Checklist

- [x] The diff is minimal and focused on one concern.
- [x] No secrets, credentials, tokens, or private paths are introduced.
- [x] Shell scripts touched pass `bash -n`.
- [x] Python touched compiles (`python3 -m py_compile`).
- [x] `settings.json` still parses (`python3 -m json.tool settings.json`) if changed. (Not changed.)
- [x] No existing safety check / hook was weakened or bypassed. (The landing's `git config` writes
  run inside the Stop hook process, as R4 requires; `pretool-bash-safety.sh` still denies them to
  agent Bash calls.)
- [ ] Docs/INDEX updated if structural files changed. (README, PUBLIC-CORE.md and the overlay example
  are updated; `scripts/install/INDEX.md` and `tests/INDEX.md` are doc-sync output and were not
  hand-edited, see "Out of scope, found".)

## Notes for reviewers

All runtime evidence comes from the sandbox kit (`harness-repair-plan/tools/`, `sb-setup.sh` with a
local copy of a python 3.12 venv, no network) built from this branch at 98d153ad (acceptance 1-16 and
the extra runs, before commits 47-50), at 26a7ea7a (acceptance 11 and its cost, `n1`, `pullsh` and
`fswatchpop` again, in `work/evidence/review-r4/`), at 96bcb8f2 (acceptance 11 and its cost,
review V1-1's repro, in `work/evidence/review-v1/`), at 921b5128 (acceptance 11 and its cost,
review NV-1's repro, the NF-3 and V1-1 repros again, in `work/evidence/review-nv1/`), at
10d7d254 (the unit runs, the trial merge with PR #6 and the privacy scan, in
`work/evidence/review-nv1v/`, and the "before" of review NV1-2's repros, in
`work/evidence/review-nv12/`), at 760f06e7 (those repros after, the unit runs, the trial merge
with PR #6 and the privacy scan, in `work/evidence/review-nv12/`, and the "before" of review NVF's
repros, in `work/evidence/review-nvf/`) and at this head, 1071ad39 (those repros after, the unit
runs, the trial merge with PR #6 and the privacy scan, in `work/evidence/review-nvf/`), and, for
every other "before", from a
clone of d625284 (P1 merged), plus scratch clones. Commits 47-49 change `scripts/install/land`
(two lines of the landed fast path), `repaired()` and its two calls in `scripts/install/render-settings`, `safe_pull`
in `hooks/git-fswatch.sh` and `tests/test_landing.py` only; commit 50 changes the end of the landed
repair in `scripts/install/land` (its log result, after the fast path's exit) and in
`render-settings land --repair` (when its notice parts are given), and `tests/test_landing.py`;
commit 51 changes `repair_pop`'s result, `repaired()` and the repair branch of `land()` in
`scripts/install/render-settings`, the same end of the landed repair in `scripts/install/land` (its
log result), and `tests/test_landing.py`; commit 52 rewords `cmd_land`'s docstring in
`scripts/install/render-settings` only (its syntax tree with the docstrings blanked is 921b5128's,
`review-nv1v/comment-only.txt`), so the kit runs at 921b5128 ran 10d7d254's code and were not
run again there; commit 53 changes `repaired()` in `scripts/install/render-settings` (a control
character in a refused path's name as `?`) and commit 54 the end of the landed repair in
`scripts/install/land` (the notice and log result of a repair run that fails outright), each with
`tests/test_landing.py`: neither changes what the kit runs at 921b5128 printed (no refused name
there holds a control character, and no repair run there fails), so they were not run again
either; nor were commits 55 and 56 (a line-break character in a refused path's name as `?` as well,
and a repair run that fails with nothing on stdout named and logged as failed too, each with
`tests/test_landing.py`), for the same reasons. Every scenario of this round ran
with `env -i` in a PID namespace of its own (`unshare --pid --fork --mount-proc` around `ns.sh` or
`ns-alt.sh`), so no landing in a kit sees another kit's processes or the CI suite's, which ran on
the host at the same time. Evidence paths below are under the scratch directory: `work/evidence/`
holds the after runs on 98d153ad's kit (`*-after.txt`, `review-r2/`; all of them run again at
98d153ad, after review round 3) and every before run on d625284's kit (`*-before.txt`: round 1's,
d625284 has not moved, plus the later rounds' new scenarios); `work/evidence/review-r3/` holds
review round 3's fix (N1 on 1d10ae00's kit in `prevhead/`, the cost comparison, its tests before and
after, the repeated test runs); `work/evidence/review-r4/` holds the round-4 verification's fixes
(review NF-1's experiment: the cost matrices, the landing alone, the gap scenarios; NF-2's and NF-3's
before/after; 26a7ea7a's re-runs), with its scripts in `nf1/` (`payloads/nf1.sh`, `nf1land.sh`,
`nf1hole.sh`, `nf1dbg*.sh`, `matrix.sh`, `landonly.sh`, `exp/`); `work/evidence/review-v1/` holds
the verification of 26a7ea7a's finding V1-1 (before on 26a7ea7a's kit, after on 96bcb8f2's: the
verifier's `verify-nf1/kit-src/landedlock.sh` and `v11/payloads/landedlock-v1.sh`, which also
prints each Stop's relayed `systemMessage` and whether `settings.json` parses), its test before and
after, and 96bcb8f2's acceptance 11, cost, unit runs and trial merge (runners in `v11/`);
`work/evidence/review-nv1/` holds the verification of 96bcb8f2's finding NV-1 (before on
96bcb8f2's kit, after on 921b5128's: the verifier's `verify-v11-1/kit-src/v11doc.sh`, cases
`lock-doc` and `lock-both`, and its `nf3up.sh` and `v11.sh` again), its tests before and after, and
921b5128's acceptance 11, cost, unit runs and trial merge (runners in `nv1/`: `build.sh`, `run.sh`,
`sel.sh`, `acc.sh`, `ut.sh`); `work/evidence/review-nv1v/` holds the verification of 921b5128
(its findings NV1-V1 and NV1-V2): the check that commit 52 changes a docstring only, and this
head's unit runs, trial merge and privacy scan (runners in `nv1v/`: `comment-only.py`, `ut.sh`,
`merge-p8.sh`, `privacy-new.sh`); `work/evidence/review-nv12/` holds the verification of
10d7d254 (its findings NV1-2-1 and NV1-2-2): the verifier's `verify-nv1-2/kit-src/oddpath.sh`
(cases `tab`, `newline`, `space`, `nonutf8`) and `crash.sh`, unchanged, on a kit of 10d7d254
(`*-before.txt`) and of this head (`*-after.txt`), their comparison (`compare.txt`), two extra
scenarios of this round (`oddstrict-*.txt`, `oddalone-*-after.txt`; scripts in
`nv12/kit-src-extra/`), the new tests before and after, and this head's unit runs, trial merge and
privacy scan (runners in `nv12/`: `clone.sh`, `build.sh`, `repro.sh`, `compare.sh`, `mixtree.sh`,
`nt.sh`, `ut.sh`, `merge-p8.sh`, `privacy-new.sh`); `work/evidence/review-nvf/` holds the
verification of 760f06e7 (its findings NVF-1 and NVF-2): the verifier's `verify-final/kit-src/`
scenarios (`odd.sh` with its U+2028 and U+0085 cases and the others, `crash.sh`, `notice.sh`,
`upg.sh`; this round adds to `odd.sh` a U+2029 case, `ps`, and the parse of `auto-commit.sh`'s line
as the coordinator reads it, `splitlines()[-1]`) and review NV1-2's `oddstrict.sh`, 26 runs per kit,
on a kit of 760f06e7 (`*-before.txt`) and of this head (`*-after.txt`), their comparison
(`compare.txt`), the new tests before and after, and this head's unit runs, trial merge and privacy
scan (runners in `nvf/bin/`: `build.sh`, `scen.sh`, `matrix.sh`, `compare.sh`, `newtests.sh`,
`ut.sh`, `merge-p8.sh`, `privacy-new.sh`; scenarios in `nvf/kit-src/`); `r3/`, `fix/` and `acc2/` hold the
earlier rounds' experiments that this text still cites. Two inputs no later round touches come from round 1: the mutation checks (`work/evidence/mutations.txt`) and the
CLI-binary experiment (`work/evidence/experiments.txt`). Scenario scripts (outside the repository):
`live-home.sh`, `pulls.sh`, `stop.sh`, `assert-landed.sh`, `semdiff.py`, `seed-standins.sh`,
`scen.sh` (one case per acceptance test and the extra runs; the current copies, with the cases
`pullsh` and `fswatchpop` of round 2's fixes and the case `n1` and the cost variant `change` of round
3's, are in `work/r4/payloads-src/`), review round 2's repro scripts (`work/r4/payloads-vr2/`) and
the runners `work/r4/acc.sh` and `work/r4/cost.sh` (this head's cost: `v11/cost-v1.sh`, the same
runner with the before kit rebuilt from d625284 as `work/kit-v1-master`). `live-home.sh` starts the kit home's HEAD
reflog afresh before it moves the home to the pre-P7 revision: the kit's harness is a copy of a
clone made after P7, whose clone entry the landing leaves to init (D13); a live home cloned before
P7 has no such entry. Values the migration or the seeding reads are never printed: counts and
sha256 only, stand-ins in acceptance 10.

Review round 1 found 7 medium and 14 low issues (fixed in commits 13-29). Review round 2 found 4
medium and 13 low issues; each one's status on this head (the repro scripts of round 2 re-run on
1b58fa0a, the head after commits 30-36, in `work/evidence/verify-1b58fa0/`, and on 98d153ad in
`work/evidence/review-r2/`; every fix has a test that fails on the code before it:
`r3/evidence/new-tests-before-after.txt` for commits 30-36, 10 failed on 1962cb6's code and passed
after; `work/evidence/new-tests-before-after.txt` for commits 37-43, 9 failed with each
commit's own code files taken from its parent and passed on this head):

| Finding | Severity | Status on this head | Commit; evidence (`work/evidence/`) |
|---|---|---|---|
| F1: the daemon scan's `/proc` reads leaked "No such file or directory" on stderr | medium | fixed | 30 `516f682`; `verify-1b58fa0/f1.txt` 16 of 16 passed under a churner (round 2: 4 failures in 16), `review-r2/f1-after.txt` 8 of 8 |
| LH-1: a home whose reflog expired before a clean pull stayed `none` | medium | fixed | 31 `e3ad6eb`; `verify-1b58fa0/lh1.txt` (merge, /pull, fswatch: `upgraded`, landed), `expired-after.txt` |
| LH-2: a seeded value in 595 tracked lines refused every whole-tree checkpoint; the PR's "P8 removes most" was false | medium | fixed: such a value is not seeded (the 100-line rule); the claim corrected under "Out of scope, found" | 32 `46eb7b8`; `verify-1b58fa0/lh2.txt`, `common-after.txt`, `occ-p8-after.txt` |
| RQ-1: +549 against the +250 target, with an unsupported claim | medium | reported, not met: +621 now; the claim reworded as untested, the line density stated ("Net code lines") | - |
| F2: a failed landing's notice dropped what it had done | low | fixed | 33 `668aab2`; `verify-1b58fa0/f2.txt` |
| LH-6: a repair git refused was counted as done | low | fixed | 34 `d0abd34`; `verify-1b58fa0/lh6.txt`, `lh6b.txt` |
| LH-3: a tracked legacy hook was renamed (its repository then recorded the deletion) | low | fixed | 35 `a681272`; `verify-1b58fa0/lh3.txt` |
| RQ-7: in state `hooks` step 5 runs alone, so step 4's files stay missing; the notice said "changed" | low | wording fixed; the step-5-only run is R1's rule, disclosed | 36 `1b58fa0`; `review-r2/rq7-after.txt` |
| F3: in a `/home/<user>` layout the old `/root/.claude/...` script paths were seeded | low | fixed | 37 `6653fa9`; acceptance 14 seeds 21 values (36 before this commit, 37 on round 2's head), `review-r2/f3-after.txt`, `f3b-after.txt` (no such path in the list; the README line commits) |
| LH-7: a landed repair named no live entry it dropped | low | fixed | 38 `c3e7e8a`; `review-r2/lh7-after.txt` |
| LH-5: an owner's own doc conflict cost a repair run (100 to 120 ms, two log lines) at every Stop | low | fixed | 39 `6938778`; `review-r2/lh5-after.txt` (26 to 30 ms per run of `land`, 0 log lines) |
| RQ-4: the loop over the repositories found had no time bound (16.3 s with 3500) | low | fixed | 40 `89a619e`; `review-r2/rq4-after.txt` (8.22 s with 3500, `scan=timed-out`) |
| LH-4: a daemon started up to about 1 s after its code was written counted as stale | low | fixed | 41 `12b3aee`; `review-r2/lh4-after.txt` (case A: no restart; case B: one restart, none at the next two Stops) |
| RQ-2: a daemon whose restart fails stays stopped | low | disclosed: R8's rule (a failed restart is a notice, no retry); the D15 bullet says so | `review-r2/rq2-after.txt` |
| RQ-3: commit 1d935e4's body says more than was run | low | corrected in this text (under "Commits") | `review-r2/rq3-after.txt` |
| RQ-5: no /merge rows | low | added ("Pull paths and states") | `matrix-mergesh-*.txt`, `mergesh-detail-*.txt` |
| RQ-6: three choices without an experiment | low | rows added with their experiments (the `CLAUDE_HOME` precondition, the 60 s lock age, which list counts as empty) | `r3/exp/precond/`, `r3/exp/lock/`, `r3/exp/empty/`; `review-r2/rq6-after.txt` |

Review round 3 re-ran round 2's repro scripts on 1d10ae00 (13 fixed, 4 disclosed, as above) and
found one medium and two low new issues; commits 45 and 46 fix the medium one, each with a test
that fails on the code before it (`work/evidence/review-r3/new-tests-before-after.txt`: 4 failed
with each commit's own code files from its parent, 4 passed on this head):

| Finding | Severity | Status on this head | Commit; evidence (`work/evidence/`) |
|---|---|---|---|
| N1: on a landed home, once the CLI wrote a key the clean form leaves out (`model`), /pull exited 1 (`cannot pull with rebase: You have unstaged changes`) and fswatch's `safe_pull` returned 0 without pulling, after every later Stop too; P7's manual init leaves a home the same way, and the landing brings every upgraded home there | medium | fixed from the next Stop on: the landed fast path re-records the index stat (a pull before that Stop still meets the refusal once, under "Out of scope, found") | 45 `8ab874b`, 46 `98d153a`; `n1-after.txt` (after the Stop: `pull.sh rc=0`, `safe_pull rc=0`, HEAD at the upstream commit, the CLI's `model` kept), `review-r3/prevhead/n1-after.txt` (1d10ae00) and `n1-before.txt` (d625284 after P7's manual init): `pull.sh rc=1`, HEAD behind; `review-r3/n1-cost.txt` |
| N2: the line-density figures for the comparison files counted bytes, not columns | low | corrected ("Net code lines": characters) | - |
| N3: one unexplained failure in 11 full runs of the 100 tests (id not captured) | low | not reproduced: 4 more full runs of the 103 tests with `-rf` at 98d153ad (3 of them while acceptance runs or the CI suite used the machine), all passed; so did acceptance 17's four runs and the CI suite's run of them; left, under "Out of scope, found" (P7b) | `review-r3/n3-runs.txt` |

The round-4 verification (on 98d153a) found one medium and two low issues; commits 47-49 settle
them, each with a test that fails on the code before it (`work/evidence/review-r4/new-tests-before-after.txt`:
4 failed with each commit's own code file from its parent, all 5+3+2 selected cases passed on 26a7ea7a, and in this head's full runs):

| Finding | Severity | Status on this head | Commit; evidence (`work/evidence/review-r4/`) |
|---|---|---|---|
| NF-1: commit 46's marker file `<git common dir>/claude-settings.checked`, read at every Stop, goes against P7b.md's "add no flag, marker or counter file" | medium | decided by experiment: kept, as a recorded departure ("Decisions applied", the N1 row of the technical choices). Of three variants without a file of their own, (a) diffs at every Stop (+92 to +102 ms in the landing with a real change, over budget), (b) "newer than the index" brings N1 back after an index write between the CLI's write and the Stop, (c) "an mtime other than the index's" re-runs the filter at every Stop once git's whole-second racy test makes the Stop's `git status` rewrite the index. The experiment also found the marker's own gap, fixed: the clean file put back with an older mtime after a real change was diffed | 47 `d864104`; `nf1-cost-summary.txt`, `nf1-land-only-summary.txt`, `nf1-hole-kit.txt`, `nf1-explore.txt`, `nf1-variant-c-rewrite.txt` |
| NF-2: fswatch's `safe_pull` with untracked files alone reported a failed restore ("MANUAL INTERVENTION REQUIRED", rc 1) or popped an older entry (a regression of commit 43's pop status on the untracked-files defect) | low | fixed: the push's `refs/stash` before and after, as in `hooks/pull.sh` | 48 `31368cb`; `nf2-fswatch-untracked.txt` (d625284: `No stash entries found`, `Stashed changes restored`, rc 0, the older change applied; 98d153a: `MANUAL INTERVENTION REQUIRED`, rc 1, or the older change applied; this head: `Nothing was stashed`, rc 0, the entry kept), `pullsh-after.txt`, `fswatchpop-after.txt` |
| NF-3: an unmerged `settings.json` that git refused to repair (a lock) was counted among the "other conflicted path(s) left as they are" | low | fixed: named apart, as the path the next Stop repairs | 49 `26a7ea7`; `nf3-notice.txt` (before: `2 other conflicted path(s) left as they are`; after: `settings.json still conflicted: git refused its repair, tried again at the next turn end; 1 other conflicted path(s) left as they are`) |

The verification of 26a7ea7a found one low issue, the landed-home counterpart of NF-3, which commit
49 did not reach; commit 50 fixes it, with a test that fails on the code before it
(`work/evidence/review-v1/new-test-before-after.txt`: it fails with 26a7ea7a's `land` and
`render-settings`, and with commit 50's `land` alone (no notice), and with commit 50's
`render-settings` alone (`result=repaired`); it passes with both):

| Finding | Severity | Status on this head | Commit; evidence (`work/evidence/review-v1/`) |
|---|---|---|---|
| V1-1: on a landed home whose later pull left `settings.json` unmerged, while a git lock refused the repair the landing gave no notice (the coordinator relayed only the checkpoint's `Checkpoint snapshot refused by the settings filter` line), and `logs/landing.log` said `result=repaired` right after `repair resolved=0 ... unmerged-left=1`; until the next Stop `settings.json` keeps its conflict markers, so a session that starts then reads an invalid file | low | fixed: `render-settings land --repair` gives `repaired()`'s parts while `settings.json` stays unmerged too, so the notice reads `settings.json still conflicted: git refused its repair, tried again at the next turn end` as on an upgraded home, and `land` logs `result=repair-refused`; without the lock the next Stop repairs the file as before. The window itself stays (the lock is git's; nothing in the landing can write `settings.json` while it is held) | 50 `96bcb8f`; `v1-1-before.txt` and `v1-1-after.txt` (the verifier's `landedlock.sh`; before: no landing notice, `result=repaired`; after: the notice, `result=repair-refused`, then `result=repaired` and nothing unmerged once the lock is gone), `v1-1-detail-before.txt`, `v1-1-detail-after.txt` (two Stops with the lock held, then one without: `settings.json: JSON no, conflict-marker lines 3` while held, `JSON yes` after, on both heads) |

The verification of 96bcb8f2 found one low issue, the doc-sync counterpart of NF-3 and V1-1;
commit 51 fixes it, with tests that fail on the code before it
(`work/evidence/review-nv1/new-tests-before-after.txt`: the new test's two cases and LH-6's test
fail with 96bcb8f2's `land` and `render-settings`; with commit 51's `land` alone 4 fail, the V1-1
test among them, and with its `render-settings` alone 1 (`result=repaired` for `CLAUDE.md` alone);
with both, all 6 selected cases pass, the unchanged NF-3, V1-1 and LH-7 tests among them):

| Finding | Severity | Status on this head | Commit; evidence (`work/evidence/review-nv1/`) |
|---|---|---|---|
| NV-1: the landed repair also takes an `INDEX.md` or `CLAUDE.md` whose stash change is doc-sync's date lines only; while a git lock refused that repair, such a file alone gave no notice and `logs/landing.log` said `result=repaired`, and with `settings.json` refused as well the notice counted it among the "1 other conflicted path(s) left as they are", although the next Stop takes it from upstream | low | fixed: the `settings.json` case is the general one now. `repair_pop` returns the paths whose checkout or rm git refused; `repaired()` names them all apart ("CLAUDE.md, settings.json still conflicted: git refused its repair, tried again at the next turn end") and counts only the rest as other paths; `render-settings land --repair` exits 1 while one is refused, and `land` logs that as `result=repair-refused` (in place of commit 50's `git ls-files -u -- settings.json`). The NF-3 and V1-1 notices for `settings.json` alone keep their wording; without the lock the next Stop repairs both paths as before | 51 `921b512`; `nv1-lock-doc-before.txt` and `nv1-lock-doc-after.txt` (the verifier's `v11doc.sh lock-doc`, doc-sync's `CLAUDE.md` alone; before: no landing notice, `result=repaired`; after: `CLAUDE.md still conflicted: git refused its repair, tried again at the next turn end`, `result=repair-refused`), `nv1-lock-both-before.txt` and `nv1-lock-both-after.txt` (`lock-both`, with `settings.json`; before: `settings.json still conflicted: ...; 1 other conflicted path(s) left as they are`; after: `CLAUDE.md, settings.json still conflicted: ...`, no other path), and on both heads the next Stop without the lock: `2 file(s) a pull left conflicted taken from upstream (1 doc-sync)` (`1 file(s) ... (1 doc-sync)` for `CLAUDE.md` alone), `result=repaired`, nothing unmerged, no conflict marker; the NF-3 and V1-1 repros again (`nf3up-*.txt`, `v11-lock-*.txt`, `v11-lock-owner-*.txt`, `v11-nolock-*.txt`): the same output on both heads but for the commit ids |

The verification of 921b5128 found no defect in the code and two low wording issues; commit 52
and this text fix them (a docstring and a count in this text: no test can fail before either):

| Finding | Severity | Status on this head | Commit; evidence (`work/evidence/review-nv1v/`) |
|---|---|---|---|
| NV1-V1: since commit 51, `render-settings land --repair` exits 1 while git refuses a path, with the notice part on stdout, but `cmd_land`'s docstring still gave exit 1 as the failed-step case only (the usage text, `render-settings:34`, and `land()`'s docstring, `:1443-1444`, already said it); `land`'s comment on `settings()` (`land:226`) names only the notice part or the failed step | low | fixed: the docstring (`render-settings:1494-1496`) reads "stdout is one line: the notice part, or the failed step (exit 1; with --repair also a refused path)", on its own three lines (net code lines unchanged). `land:226` is left as it is: it says what `$out` holds, which is one of those two either way, and `land:228` says that a path git refused makes render-settings exit 1. The exit is checked by the V1-1 and NV-1 tests (`result=repair-refused` with the notice; `tests/test_landing.py:728`, `:793`) | 52 `10d7d25`; `comment-only.txt` (the syntax tree of `render-settings` with its docstrings blanked is 921b5128's; net code +620 and +59 as before; `render-settings` 4 of 1555 lines over 100 characters, `land` 49 of 248, as before) |
| NV1-V2: the trial-merge paragraph ("Files P8 (PR #6) also touches") said that "this PR's seven code and test files" are byte-identical after the merge with PR #6; outside the five files both PRs change, this PR changes nine (the seven compared, `hooks/lib/claude_home.py` and `settings.machine.example.json`), and the verifier's own trial merge found all nine byte-identical | low | fixed in this text: the trial merge of this head compares all nine (each byte-identical after the merge) and checks every line this PR adds to the five shared files | `merge-p8-trial.txt` (trial merge commit 2ddbdd5c) |

The verification of 10d7d254 found two low issues, one that commit 51 introduced and one older;
commits 53 and 54 fix them, each with a test that fails on the code before it
(`work/evidence/review-nv12/new-tests-before-after.txt`: the NV1-2-1 test's two cases fail with
10d7d254's `render-settings`, the NV1-2-2 test with 10d7d254's `land`, alone and with its
`render-settings`; all three cases pass on this head):

| Finding | Severity | Status on this head | Commit; evidence (`work/evidence/review-nv12/`) |
|---|---|---|---|
| NV1-2-1 (introduced by commit 51): `repaired()` wrote the paths git refused to repair into the notice verbatim, so a tab or a newline in the name of a doc-sync directory broke the one-line notice: with a newline `land` printed two lines, with a tab `auto-commit.sh`'s `{"systemMessage": ...}` line was not valid JSON; either way that Stop relayed nothing, the refused-snapshot notice on the same line included | low | fixed: each named path has its control characters (`\x00`-`\x1f`, `\x7f`) replaced by `?` before it enters the notice (`render-settings:1415`, the docstring `:1410-1411`; net code 0 lines; commit 55 adds `\x80`-`\x9f`, U+2028 and U+2029, review NVF-1); a name without one (a space, a byte that is not UTF-8) is named as before, and the next Stop without the lock repairs the paths as before | 53 `25166ef`; `oddpath-tab-*.txt`, `oddpath-newline-*.txt` (with `index.lock` held, before: no `systemMessage` relayed, `land`'s own line holds the tab (`^I`) or is split in two, `parses: no`; after: `Harness landing: settings.json, tools/odd?dir/INDEX.md still conflicted: git refused its repair, tried again at the next turn end.` relayed after the refused-snapshot notice, `parses: yes`; without the lock both heads repair both paths, `result=repaired`), `oddpath-space-*.txt` and `oddpath-nonutf8-*.txt` (the same on both heads), `compare.txt`; `test_a_refused_path_with_a_control_character_keeps_the_notice_one_line` (tab, newline; since commit 55 also U+2028 and U+0085; `tests/test_landing.py:829`) |
| NV1-2-2 (pre-existing): when `render-settings land --repair` failed outright (an exception), `cmd_land` printed its failed step, `settings`, and exited 1; the landed branch of `land` relayed "Harness landing: settings." and, since commit 51, logged `result=repair-refused`, the result of a path git refused to repair. The technical choices' notice-wording row said that before commit 51 such a run was logged `repaired`; that held only while `settings.json` was not among the unmerged paths | low | fixed: `land` maps that failed step to "the settings repair failed (see logs/landing.log); it runs again at the next turn end" and logs `result=repair-failed` after render-settings' `land: failed: <type>` line (`land:228-230`; net code +1 line; since commit 56 told by the exit status and an empty or `settings` stdout, review NVF-2); a refused path is still `repair-refused`, a repair `repaired`, and the upgraded landing's failed-step notice is unchanged. The row is corrected: commit 50 logged such a run `repair-refused` while `settings.json` was unmerged after it (`git ls-files -u -- settings.json`; the verifier's `verify-nv1-2/ev/crash-before.txt` on 96bcb8f2) and `repaired` only when it was not | 54 `760f06e`; `crash-*.txt` (`repair_pop` made to raise, one inserted line: before `Harness landing: settings.` and `result=repair-refused`, after the sentence and `result=repair-failed`; with the file restored both heads repair `settings.json`, `result=repaired`); `test_a_landed_repair_that_fails_outright_says_so_and_is_logged_apart` (fault injection; `tests/test_landing.py:745`) |

Two more cases of odd names that this round's extra scenarios found, outside both findings and not
changed here, are under "Out of scope, found" (a refused name that is not UTF-8 under a strict
stdout error handler; a doc-sync file alone under a directory whose name git quotes).

The verification of 760f06e7 found two low issues in the lines of commits 53 and 54; commits 55 and
56 fix them, each with a test that fails on the code before it
(`work/evidence/review-nvf/new-tests-before-after.txt`, this head's tests with each commit's own
code file taken from its parent: the NVF-1 test's two new cases fail with 760f06e7's
`render-settings`, the NVF-2 test with 7a401465's `land`; all 5 selected cases pass on this head).
Of the 26 scenarios run on both kits, the 7 of the two findings differ and the other 19 print the
same on both, ids and times normalised (`review-nvf/compare.txt`):

| Finding | Severity | Status on this head | Commit; evidence (`work/evidence/review-nvf/`) |
|---|---|---|---|
| NVF-1 (left by commit 53): `repaired()`'s replacement covered `\x00`-`\x1f` and `\x7f` only, but the Stop coordinator reads `auto-commit.sh`'s last stdout line with `str.splitlines()` (`hooks/stop-workflow-coordinator.py:185`), which also breaks at U+0085, U+2028 and U+2029: with one of them in the name of a refused doc-sync directory, `auto-commit.sh`'s `{"systemMessage": ...}` line still parsed as JSON, but the coordinator parsed only its tail, so that Stop relayed nothing, the refused-snapshot notice on the same line included | low | fixed: the replaced class also holds `\x80`-`\x9f` (the C1 controls, U+0085 among them), U+2028 and U+2029 (`render-settings:1415`; the docstring `:1411` says "a control or line-break character"; net code 0 lines); a name without one (a space, a byte that is not UTF-8) is named as before, and the next Stop without the lock repairs the paths as before | 55 `7a40146`; `odd-ls-*.txt` (U+2028; `CLAUDE.md` and `INDEX.md`), `odd-nel-*.txt` (U+0085; both), `odd-ps-CLAUDE-*.txt` (U+2029, a case this round adds): with `index.lock` held, before: no `systemMessage` relayed at all, `land`'s line holds the character as it is, `auto-commit.sh`'s line `parses=yes` but the coordinator's `splitlines()[-1]` of it `parses=no`; after: `Checkpoint snapshot refused by the settings filter (render-settings clean): nothing written, see logs/checkpoint.log; Harness landing: agents/a?b/CLAUDE.md, settings.json still conflicted: git refused its repair, tried again at the next turn end.` relayed, both `parses=yes`; without the lock both heads repair both paths, `result=repaired`; the tab, newline, mixed-control and space cases print the same on both heads; `test_a_refused_path_with_a_control_character_keeps_the_notice_one_line` (its U+2028 and U+0085 cases, which also parse the coordinator's `splitlines()[-1]` of `auto-commit.sh`'s line; `tests/test_landing.py:829`) |
| NVF-2 (left by commit 54): `land` told a failed landed repair by its stdout alone, exactly `settings`; a run that failed with nothing on stdout (`render-settings` does not compile, so python3 exits 1 before `cmd_land`; or an exception escapes `cmd_land`'s `try`, such as `print()`'s `UnicodeEncodeError` under a strict stdout error handler) was logged `result=repair-refused`, with no notice | low | fixed: `land` decides by the exit status and stdout: a non-zero exit with stdout empty or `settings` is `result=repair-failed`, with "the settings repair failed (see logs/landing.log); it runs again at the next turn end"; any other non-zero exit (a refused path, its notice part on stdout) is `repair-refused`, exit 0 `repaired` (`land:229-230` in place; net code 0 lines) | 56 `1071ad3`; `crash-syntax-*.txt` (the verifier's `crash.sh syntax`, an unmatched `)` as `render-settings`' second line; before: the Stop relays the refused-snapshot notice alone, the log holds python3's `SyntaxError` and `result=repair-refused`; after: that notice and `Harness landing: the settings repair failed (see logs/landing.log); it runs again at the next turn end.`, `result=repair-failed`; with the file restored both heads repair `settings.json`, `result=repaired`), `crash-pull_stash-*.txt` and `crash-repaired-*.txt` (an exception inside `cmd_land`'s `try`: the same on both heads), `oddstrict-*.txt` (with `PYTHONIOENCODING=utf-8:strict`: before no stdout and `result=repair-refused`, after the sentence and `result=repair-failed`; under "Out of scope, found"); `test_a_landed_repair_whose_render_settings_does_not_compile_says_it_failed` (fault injection; `tests/test_landing.py:768`) |

Commit 44 changes comments only: the first CI run after review round 2's fixes (at bddf8df5,
`work/ci/out-head-bddf8df/`) found that a comment commit 37 added named the root home's harness
path, which the public-core step's author-path residue audit counted as one new failure (49
against d625284's 48); every run in this text was then repeated at 98d153ad (and the ones `review-r4/` names on 26a7ea7a, those `review-v1/` names on 96bcb8f2, and those
`review-nv1/` names on 921b5128).

Four existing tests changed with the fixes they cover, and none checks less than before: the
seeding test now expects the previous home's script path left out (13 values instead of 14, plus an
assertion that its previous settings do hold that path; commit 37), and the cut-scan test expects
the notice's new wording "stopped at its time limit" (commit 40), and the real-change test of commit
46 gains a step (a later index write runs no diff; commit 47). Commit 50 moves the setup of
`test_a_landed_repair_names_the_live_entries_it_drops` (review LH-7), its three assertions included,
into the helper `landed_settings_conflict()` that the new V1-1 test shares; that test checks the
same as before. In commit 51, LH-6's test (a doc-sync `commands/INDEX.md` the lock refused) expects
the notice that names that path where it expected no notice (review NV-1); its other assertions
are unchanged. Commit 55 adds two cases (U+2028, U+0085) and one assertion (the coordinator's
`splitlines()[-1]` parse of `auto-commit.sh`'s line) to commit 53's test; its tab and newline cases
and its other assertions are unchanged. No test was skipped or deleted.

Commits 42, 43 and 48 are outside this prompt's file list: P7b.md's DO NOT names `hooks/pull.sh`
and git-fswatch.sh's sync and pull functions; the review of PR #6 routed the first two defects to
this phase and the round-4 verification the third (NF-2). Each edit is the one the routing named
(`hooks/pull.sh`: STASHED only when `refs/stash` changed across the push; `hooks/git-fswatch.sh`
`safe_pull`: the pop's own exit status, and the same `refs/stash` comparison for its push), each
with a test that fails before; nothing else in either file changed.

### What happens today (facts 1-9, re-run on d625284's code)

1. Pull paths, each from a fe7700c8 home (old pull code), conflicting live edit / mergeable live edit:
   fswatch `safe_pull`: `CONFLICT (content): Merge conflict in settings.json`, then
   `[SUCCESS] Pull successful` and `[SUCCESS] Stashed changes restored`, `safe_pull rc=0` / ` M`,
   `rc=0`; /pull (`hooks/pull.sh`): `pull.sh rc=1`, `The stash entry is kept in case you need it
   again.` / ` M`, `rc=0`; merge pull: `merge rc=1`, `error: Your local changes to the following files
   would be overwritten by merge:`, HEAD unchanged, both edits.
2. Conflicting live edit (`model` changed + one stand-in allow): `UU settings.json`, `stash: 1`,
   `settings.json JSON: no`; the allow alone: ` M settings.json`, `stash: 0`, JSON.
3. New code without filter, overlay or record, on the conflicted home: the Stop's notice is
   `Checkpoint snapshot refused by the settings check (render-settings check --staged): nothing
   written, see logs/checkpoint.log`; `UU settings.json` stays, no overlay.
4. P7's manual commands on the conflicted home: `bootstrap rc=1` after `render-settings: wrote
   settings.machine.json (mode 0600) from ORIG_HEAD:settings.json`, `bootstrap: settings filter
   claude-settings registered (local git config)`, `render-settings: settings.json is not a valid
   JSON object; fix it, or re-run with --force to replace it`.
5. `render-settings migrate --from 09ab15bc` on d625284: `overlay env GIT_AUTO_PUSH: '1'`.
6. A pre-landing session (env `GIT_AUTO_PUSH` "1", no `CLAUDE_HOME`): `checkpoint refs on origin
   after 6 s: 1`.
7. The pre-P0 hook copies: after a plain-shell commit, `refs/backups on origin after 6 s: 1`.
8. `registrations: 83, with a harness script: 83, distinct files: 82, missing here: 0` (fe7700c8's
   settings.json against d625284's tree and against this branch's).
9. A home that pulled P7 alone (f8c18c2) into S3, origin then at this branch: f8c18c2's `safe_pull`
   prints `error: Pulling is not possible because you have unmerged files.` and still `Pull
   successful` / `Stashed changes restored`, `safe_pull rc=0`; its `pull.sh`: `settings.json: needs
   merge`, `rc=1`; `git pull rc=128`; `HEAD is still f8c18c2: yes`. P7b's code never reaches such a
   home (out of scope, below).

Evidence: `work/evidence/facts1-before.txt` (1, 2), `1-before.txt` (3), `facts-before.txt` (4, 8),
`4-before.txt` (5), `6-before.txt` (6), `9-before.txt` (7), `fact9-before.txt` (9); on 98d153ad's kit
`work/evidence/facts1-after.txt` (1, 2: the same lines; the old pull code runs there),
`facts-after.txt` (4: `bootstrap rc=1`, the same three lines; 8: the same counts) and
`fact9-after.txt` (the same lines, `HEAD is still f8c18c2: yes`). Commit 43 changes fact 1 for
fswatch's pop on a home that runs this head's `git-fswatch.sh` (scenario `fswatchpop`); the facts
above are what the pre-P7 code does.

### Pull paths and states

Every pull path against every live edit, from a pre-P7 home at fe7700c8 with the pre-P0 hook
installed, then a pre-landing session's Stop (`scen.sh matrix`; "assert-landed" counts the nine
lines of acceptance 1-4 that read as required):

| Path | Live edit | After the pull | After the Stop, this branch | After the Stop, d625284 |
|---|---|---|---|---|
| fswatch | none (S1) | `settings=clean HEAD=NEW stash=0` | Stop ok=1 state=landed assert-landed=9/9 notice: landed | Stop ok=1 overlay=absent settings=json filter=unset |
| fswatch | cli-merge (S2) | `settings=_M HEAD=NEW stash=0` | Stop ok=1 state=landed assert-landed=9/9 notice: landed | Stop ok=1 overlay=absent settings=json filter=unset |
| fswatch | cli-conflict (S3) | `settings=UU HEAD=NEW stash=1` | Stop ok=1 state=landed assert-landed=9/9 notice: landed | Stop ok=1 overlay=absent settings=not-json filter=unset |
| fswatch | local commit (S4) | `settings=UU rebase-stopped HEAD=NEW stash=0` | Stop ok=1 state=upgraded assert-landed=1/9 notice: waits (S4) | Stop ok=1 overlay=absent settings=not-json filter=unset |
| /pull | none (S1) | `settings=clean HEAD=NEW stash=0` | Stop ok=1 state=landed assert-landed=9/9 notice: landed | Stop ok=1 overlay=absent settings=json filter=unset |
| /pull | cli-merge (S2) | `settings=_M HEAD=NEW stash=0` | Stop ok=1 state=landed assert-landed=9/9 notice: landed | Stop ok=1 overlay=absent settings=json filter=unset |
| /pull | cli-conflict (S3) | `settings=UU HEAD=NEW stash=1` | Stop ok=1 state=landed assert-landed=9/9 notice: landed | Stop ok=1 overlay=absent settings=not-json filter=unset |
| /pull | local commit (S4) | `settings=UU rebase-stopped HEAD=NEW stash=0` | Stop ok=1 state=upgraded assert-landed=1/9 notice: waits (S4) | Stop ok=1 overlay=absent settings=not-json filter=unset |
| merge | none (S1) | `settings=clean HEAD=NEW stash=0` | Stop ok=1 state=landed assert-landed=9/9 notice: landed | Stop ok=1 overlay=absent settings=json filter=unset |
| merge | cli-merge (S2) | `settings=_M HEAD=old stash=0` | Stop ok=0 state=no P7b code (HEAD old) assert-landed=1/9 no notice | Stop ok=0 overlay=absent settings=json filter=unset |
| merge | cli-conflict (S3) | `settings=_M HEAD=old stash=0` | Stop ok=0 state=no P7b code (HEAD old) assert-landed=1/9 no notice | Stop ok=0 overlay=absent settings=json filter=unset |
| merge | local commit (S4) | `settings=UU merge-stopped HEAD=old stash=0` | Stop ok=1 state=upgraded assert-landed=1/9 notice: waits (S4) | Stop ok=1 overlay=absent settings=not-json filter=unset |

/merge (`/merge origin/master`, which runs the home's own pre-P7 `hooks/merge.sh`) behaves like the
merge rows (`scen.sh matrix-mergesh` above, `mergesh-detail` below): S1 merges (`merge.sh rc=0`, HEAD
at NEW) and lands at the Stop; S2 and S3 are refused (`merge.sh rc=2`, `refusing to merge in_place
with uncommitted changes present`, HEAD unchanged, ` M settings.json`), so no P7b code reaches the
home; S4 stops mid-merge (`merge.sh rc=1`, `UU settings.json`, `MERGE_HEAD` present) and the landing
waits:

| Live edit | /merge (the home's old `merge.sh`) | After the Stop, this branch | After the Stop, d625284 |
|---|---|---|---|
| none (S1) | `merge.sh rc=0 refused=0 HEAD=NEW settings= MERGE_HEAD=no` | Stop ok, state landed, notice: landed | Stop ok, state n/a (no landing code) |
| cli-merge (S2) | `merge.sh rc=2 refused=1 HEAD=old settings=_M MERGE_HEAD=no` | Stop NOT ok, state n/a (no landing code), notice: no notice | Stop NOT ok, state n/a (no landing code) |
| cli-conflict (S3) | `merge.sh rc=2 refused=1 HEAD=old settings=_M MERGE_HEAD=no` | Stop NOT ok, state n/a (no landing code), notice: no notice | Stop NOT ok, state n/a (no landing code) |
| local commit (S4) | `merge.sh rc=1 refused=0 HEAD=old settings=UU MERGE_HEAD=yes` | Stop ok, state upgraded, notice: waits (S4) | Stop ok, state n/a (no landing code) |

A home whose HEAD had not moved for longer than its reflog keeps entries (90 days, then `git gc`;
here `git reflog expire --expire=now --all`, 0 entries) and then pulls with a clean tree has one
reflog entry, whose new value declares the filter and whose old value is fe7700c8 (review LH-1;
`scen.sh expired`):

| Path | Reflog entries before / after the pull | After the pull and the Stop, this branch | Round 2's head (1962cb6) | d625284 |
|---|---|---|---|---|
| merge | 0 / 1 | `land --state` upgraded; Stop ok; assert-landed 9/9; landed overlay: present filter: set legacy post-commit active: 0 | `land --state` none; Stop ok; assert-landed 3/9; none overlay: absent filter: unset legacy post-commit active: 1 | Stop ok; n/a (no landing code) overlay: absent filter: unset legacy post-commit active: 1 |
| /pull | 0 / 1 | `land --state` upgraded; Stop ok; assert-landed 9/9; landed overlay: present filter: set legacy post-commit active: 0 | `land --state` none; Stop ok; assert-landed 3/9; none overlay: absent filter: unset legacy post-commit active: 1 | Stop ok; n/a (no landing code) overlay: absent filter: unset legacy post-commit active: 1 |
| fswatch | 0 / 1 | `land --state` upgraded; Stop ok; assert-landed 9/9; landed overlay: present filter: set legacy post-commit active: 0 | `land --state` none; Stop ok; assert-landed 3/9; none overlay: absent filter: unset legacy post-commit active: 1 | Stop ok; n/a (no landing code) overlay: absent filter: unset legacy post-commit active: 1 |

A plain `git pull` is the merge row (or the /pull rows with `pull.rebase`). In the refused merge and
/merge rows (two each) the home stays at fe7700c8 and runs only fe7700c8's code: its own coordinator blocks that
sandbox Stop on the auto_commit phase (`BLOCK(exit2)`, `"failed_phase": "auto_commit"`,
`work/evidence/matrix-refused-merge.txt`; PLAN-v2.md section 13 row P5, fixed by P1 for homes that
run P1's code); no pull brought P7 there, so there is nothing to land. Fact 9 (P7 alone, left in S3
or S4) is the one state that no pull path brings P7b to.

### What the landing writes

On an upgraded home, once (each step idempotent; a landing cut short completes at the next Stop):

- `settings.machine.json` (mode 0600, only when absent, through `render-settings migrate`):
  `modules` (paseo detected by `module_enabled` as before), `env` = the previous settings' values
  beyond the clean form + the previous code defaults + `CLAUDE_HOME`, never `GIT_AUTO_PUSH` "1";
  personal permission entries; hook groups (not the hooks upstream unregistered); other top-level
  keys (the CLI keys). From fe7700c8 (and 09ab15bc) in the sandbox: `modules: paseo=on`, `env: 14
  keys` (`GRAPHIFY_BIN`, the twelve former code defaults, `CLAUDE_HOME`), `permissions.allow: 43`,
  `hooks: 0 groups`, `other top-level keys: 6` (`work/evidence/migrate-counts-after.txt`); from 09ab15bc
  also `not migrated: GIT_AUTO_PUSH`.
- `settings.json`: in S3 taken from HEAD (index entry clean), the paths the pop staged unstaged (an
  index blob equal to the stash's, or a path the stash changed that the pop merged), the stash entry
  kept; otherwise taken from HEAD last in the settings step, by any run of the landing, for as long as
  no render has written the record; entries the overlay does not hold are dropped then and named in
  the notice by key path (`GIT_AUTO_PUSH` "1" as "not migrated", anything else the CLI wrote after
  the migration as "dropped from settings.json, as the overlay does not hold them: ..."); then
  rendered (machine form) by init step 3. On a landed home whose later pull left it unmerged: taken
  from HEAD, and the live entries upstream's side lacks (the kept stash entry holds them) named the
  same way, "... (in the stash entry)".
- local git config: `filter.claude-settings.clean`, `.smudge`, `.required` (init step 3); the record
  `<git dir>/claude-settings.applied` (render).
- `logs/`, the TMPDIR root, the protected-runtime file (init step 4, each only when absent);
  `private-literals.txt` (seeded, 0600, only while it is absent or holds nothing but blank lines);
  the pre-commit hook (init step 5).
- legacy hooks renamed to `<name>.auto-push-disabled` (count in the notice); one that its repository
  tracks (a shared `.githooks/` that core.hooksPath names) is left as it is and counted
  (`tracked-left=N`, "N tracked legacy auto-push hook(s) left as they are"); where the renamed hook
  carried the LFS step, git-lfs's own post-commit at that path (written by `git lfs update` into a
  scratch hooks directory, `-c core.hooksPath=<scratch>`; the repository's other hooks untouched;
  `git lfs update` also writes `lfs.repositoryformatversion` to that repository's own config, as
  `--force` did); stale git-fswatch daemons restarted.
- `logs/landing.log` (append-only, read by no code); `<git common dir>/claude-landing.lock` (flock
  only).
- On a landed home, at the first Stop after a write of `settings.json` (review N1): while its content
  through the filter equals the index entry, that entry re-recorded with the same mode and blob and
  then refreshed (the index content does not change; render-settings' `refresh_index` does the same);
  otherwise `<git common dir>/claude-settings.checked`, an empty marker given `settings.json`'s
  mtime, so the change is diffed once per write (any other mtime of `settings.json`, an older one
  too, is a write). Nothing is staged. The marker is the one file of the landing's own beyond the
  lock and the log: a departure from P7b.md's no-marker rule ("Decisions applied").

Seeding in the sandbox from fe7700c8's real values (printed as counts only; the same from
09ab15bc): `seeded overlay-env=14 permission-paths=3 git-e-mail=0 check-markers=4` and `not seeded,
in 100 or more tracked lines at HEAD: 1 value(s)` (21 values; the sandbox home has no git identity;
22 in acceptance 1, whose live edit adds the stand-in path `/opt/demo/bin/live-tool`; the same
counts in the `/home/alice` layout of acceptance 14, `review-r2/f3-after.txt`, where 1b58fa0a seeded
36 and round 2's head 37). Round 2 seeded 22 in the root layout: the one left out now is a word of
`CLAUDE_PROTECTED_PROCESS_FAMILY`'s former code default that this head's tracked files hold in 595
lines (see the seeding row of the technical choices and "Out of scope, found"). Per class of the
owner step this replaces (`work/evidence/classes-after.txt`, each value counted once, at its first
source):

| Class | Seeded | Sources (count) |
|---|---|---|
| account names | 6 | `CLAUDE_PROTECTED_DAEMON_TARGETS` (2), `PASEO_DAEMON_ACCOUNTS` (3), the remote's SSH form among the check-public-core.sh markers (1); the account of `PASEO_DAEMON_MODEL` adds none here (no `@`) |
| e-mail addresses | 1 | the e-mail of `CLAUDE_CHECKPOINT_EXTRA_TRAILER` (1); git `user.email` (0 in the sandbox, 1 on a home with an identity) |
| private project names | 5 | `CLAUDE_DEV_CONTAINERS` (1), `CLAUDE_PROTECTED_DAEMON_PREFIX` (1), `WORKFLOW_PRUNE_PROJECT_DIRNAME` (1), `CLAUDE_HARD_BANNED_SCRIPTS` words (2); `CLAUDE_PROTECTED_PROCESS_FAMILY` (0: the value round 2 seeded from it is in 595 tracked lines and is left out) |
| personal paths | 9 | `CLAUDE_DAEMON_RESTART_GRANT_HELPER` (1), `CLAUDE_RESTART_ACCOUNTS_ROOT` (1; `WORKFLOW_PRUNE_ACCOUNTS_DIR` is the same value), `GRAPHIFY_BIN` (1), permission paths (3), check-public-core.sh marker paths (3) |

Every class has a source. Checked against PR #6's per-class list of the owner's values
(`work/evidence/classes-after.txt`, membership counts only): its 3 `DEFAULT_ACCOUNTS` accounts and the 7
marker values (`HARD_MARKERS`, `PARAM_MARKERS`, `WS_MARKER`) are all seeded; its identity e-mail
(fe7700c8 `hooks/tests/test_git_residual_override.py:134`) is not, see "Out of scope, found".

### Changes

- `hooks/auto-commit.sh:20-24` runs `scripts/install/land` before the git-repository check and
  defines `notice()`; `:29`, `:35`, `:63` print the notice last on the exit-0 paths; `:57` joins it
  with the refused-snapshot notice. Exit status and existing output unchanged.
- `scripts/install/land` (new, 249 lines): header (:1-17), `trap 'exit 0' EXIT` (:19),
  `own_hooks` (:23), `state` (:28, the landed test), `log`/`finish` (:50-55), `legacy_hooks` (:57,
  R6: the `$HOME` scan with its 5 s limit :61, the loop's 8 s cut after the home's own repository
  :63, a tracked hook left :68-70, the LFS post-commit :74-79, the cut-scan notice :87), `stale` (:93,
  R8's candidates: the `/proc` scan and the start-time test in centiseconds :102-114),
  `restart_daemons` (:118, R8: busy, stopped, time budget, systemd, the session-started environment,
  the restart), the landed fast path with its repair gate (:178-204) and the `settings.json` stat
  (:190-202, review N1 and NF-1), lock and re-check (:205-213), the landed-home daemon retry (:214),
  S4 (:215-224), `--repair` on a landed home (:227-233; `result=repair-refused` while a path git
  refused to repair stays unmerged, from `render-settings`' exit status :228-229, reviews V1-1 and
  NV-1; a run that failed outright, nothing or its failed step on stdout, named as such and logged
  `result=repair-failed` :229-230, reviews NV1-2-2 and NVF-2), the upgraded flow (:234-241: hooks and daemons
  first, then the settings), init steps (:242-249).
- `scripts/install/render-settings`: docstring (:27-34); `cmd_check` `[info]` line for
  `GIT_AUTO_PUSH` "1" (:948-949); `_tracked_hook` (:1106) and `cmd_migrate` (:1112; `previous` input
  :1127; hooks upstream unregistered left out :1157-1166; `GIT_AUTO_PUSH` "1" left out :1173-1175 and
  named :1195-1196); the land section (:1206-1511: `_HOME_OF` :1211, `pre_pull_rev` :1228 with the
  clone-entry rule and the reflog's old values, `pull_stash` :1250 with the doc-sync fallback,
  `previous_settings` :1266, `repair_pop` :1282 (it returns the paths git refused to take, review
  NV-1), `_words`, `_paths`, `_markers`, `seed_literals` :1346 with the previous harness home's paths
  :1368-1374 and the tracked-lines rule :1388-1396, `repaired` :1409 (every path git refused to
  repair named apart, reviews NF-3 and NV-1, a control or line-break character in its name as `?`
  :1415, reviews NV1-2-1 and NVF-1), `from_head` :1420, `land` :1442 with the landed
  repair's dropped entries :1446-1458 and its notice parts and exit status 1 while a path git
  refused stays unmerged (:1455, :1459, reviews V1-1 and NV-1), `cmd_land` :1493); the `land`
  subcommand in `main` (:1532-1534, :1545-1550).
- `scripts/bootstrap`: `--steps <list>` (usage :6, :22-24; :72-73; parsing :89-91); steps 1, 3, 4 and
  5 wrapped in `if _run N; then ... fi` (:159, :301, :343, :409), step 2 skipped unless named (:240),
  the step 2 comment (:238-239); the exit after a `--steps` run (:476-478). Step bodies unchanged.
- `hooks/lib/claude_home.py:189-200` `settings_env()`; `:223-225` the `env` subcommand.
- `hooks/lib/checkpoint-core.sh:320-325` `_checkpoint_rate_limited_push`: the push switch (R7).
- `hooks/pretool-bash-safety.sh:8-14`: the pre-landing knobs, before the script-relative
  `CLAUDE_HOME` assignment.
- `hooks/lib/subagent_restart.py:826-832`: `CLAUDE_RESTART_ACCOUNTS_ROOT` from the rendered settings.
- `hooks/pull.sh:28`, `:34-42`: STASHED only when `refs/stash` changed across the push (routed by
  PR #6's review).
- `hooks/git-fswatch.sh` (`safe_pull`): `:197-209` stashed only when `refs/stash` changed across the
  push (review NF-2); `:223-224` the pop's own exit status decides (routed by PR #6's review).
- `README.md`: the `--steps` row (:127), "Upgrading a home that predates the overlay" (:132-146), the
  overlay bullet (:183-185), the private-literal paragraph (:276-280). `PUBLIC-CORE.md:46-49`,
  `:70-72`. `settings.machine.example.json:2` (`_about`) and `:92` (`_private_literals.about`).
- `tests/test_landing.py` (new, 90 test cases).

### Commits

1. `ef5867b` (R3): migrate never writes GIT_AUTO_PUSH "1"; the settings check names it
2. `49938fd` (R3): migrate leaves out hooks that upstream unregistered
3. `34d4378` (R4): bootstrap --steps runs chosen init steps without a terminal or the venv
4. `5042eef` (R7): sessions started before the landing read the rendered settings
5. `4371b0c` (R2, R3, R5): render-settings land: repair, migrate and seed for the landing
6. `e48950a` (R1, R6, R8, R9): the landing runs from hooks/auto-commit.sh at every Stop
7. `d8ead41` (R10): docs name the landing as the overlay's and the list's other writer
8. `d6a5200` (R11): tests for the landing, migrate's exclusions and the pre-landing env rule
9. `0013ed2` (R2): a merge stopped on a home still at pre-P7 code gets the S4 notice
10. `c872831` (R1): the landed test compares only the hooks step 5 installs
11. `15a248a` (R8): a stale daemon in its git work holds the landing before the settings
12. `dc0dde8` (R2): every conflicted pop is undone, and a merged pop's dropped entry is not looked for
13. `1ea4dee` (R8, R9): a zombie named like the daemon no longer stops the landing
14. `f4f7db8` (R8): a daemon a pre-landing session started loses that session's push switch
15. `b998b28` (R8): only the harness home's own busy daemon holds the landing
16. `79e5511` (R8): a landed home tries stale daemons again at every Stop
17. `2d9dc29` (R1, R6, R8): the landing keeps to its 15 s bound and says when the scan was cut
18. `f4119b1` (R6): restore only the LFS post-commit, keep the repository's other hooks
19. `5a8f446` (R1, R2, R3): settings.json is taken from HEAD while no render has run
20. `b6cc085` (R2): the doc-sync exception also when the pull left settings.json alone
21. `1d935e4` (R2): a path the conflicted pop merged and staged is unstaged too
22. `375575a` (R2): a stopped squash merge is an integration in progress (S4)
23. `afd03fc` (R2, R9): the repair notice names the kept stash entry and what it left
24. `04d3f58` (R1, D13): a clone made at a filter revision is never landed
25. `c3c5a5c` (R5): seed the private-literal list only when it is absent or empty
26. `49c59c8` (R10): docs name the landed-home daemon retry and the clone rule
27. `691fd34` (R11): the daemon tests stop their stand-ins with SIGKILL
28. `61627d7` (R1): one stat call for the daemon code's mtime
29. `1962cb6` (R11): wrap the long lines this round added
30. `516f682` (R9): the daemon scan's /proc reads send their errors to /dev/null first
31. `e3ad6eb` (R1, R3): a pull after the reflog expired still finds rev
32. `46eb7b8` (R5): a value the tracked tree holds in 100 or more lines is not seeded
33. `668aab2` (R9): a failed landing's notice names what it did before the failure
34. `d0abd34` (R2, R9): a repair git refused is not counted as done
35. `a681272` (R6): a legacy hook that a repository tracks is left and counted
36. `1b58fa0` (R9): the hooks-refreshed notice no longer says the hooks changed
37. `6653fa9` (R5): a harness path under the home rev's hooks name is not seeded
38. `c3e7e8a` (R2, R9): a landed home's repair names the live entries it drops
39. `6938778` (R1): a landed home runs the repair only for a path it can take
40. `89a619e` (R1, R6): the loop over the repositories found keeps to the 15 s bound
41. `12b3aee` (R8): a daemon's start and its code's mtime are compared in centiseconds
42. `766dc8f` /pull pops only a stash entry its own push made
43. `bddf8df` fswatch's safe_pull takes a failed stash pop as failed
44. `1d10ae0` (R11): the previous-home comments name no home path
45. `8ab874b` (R1, R2): a landed home re-records settings.json's stat after a CLI write
46. `98d153a` (R1): a real settings.json change is diffed once per write
47. `d864104` (R1): a settings.json put back with an older mtime is diffed again
48. `31368cb` fswatch's safe_pull pops only a stash entry its own push made
49. `26a7ea7` (R2, R9): a settings.json git refused to repair is named apart
50. `96bcb8f` (R2, R9): a landed home's refused settings repair is named and logged apart
51. `921b512` (R2, R9): every repair git refused is named and logged apart (NV-1)
52. `10d7d25` (R11): cmd_land's docstring names --repair's exit 1 with a notice
53. `25166ef` (R9): a refused path's control characters reach the notice as ?
54. `760f06e` (R9): a landed repair that fails outright says so and is logged apart
55. `7a40146` (R9): a refused path's line breaks reach the notice as ? as well
56. `1071ad3` (R9): a landed repair that fails before printing its step says so too

Seven commit bodies say less or more than what was run, and are not amended: 26a7ea7 says that
`repaired()` "now names it on its own", but on a landed home `render-settings land --repair` gave
`repaired()`'s parts only once a path was taken from upstream, so while the lock held there was no
notice at all until commit 50 (review V1-1); e48950a says the landed
fast path is "two git calls and a cmp, then exit", but while the stash reflog is non-empty (for good
after an S3 landing) a further git call (`git ls-files -u`) runs as well, and since commit 45
`git diff-files` on `settings.json` at every Stop (the Summary above counts both);
61627d7 gives the daemon-cost range before its change as "+24.0 to +29.6 ms", and the four rounds it
refers to measured +23.8 to +29.6 ms (`acc2/evidence/11-cost-daemon-691fd34.txt`); 1d935e4 says "a
path staged by the owner after the pop, or edited since, stays staged as before", but a path the
pull's stash changed and the owner staged again after the pop is unstaged as well (review RQ-3:
` M` afterwards, its working content kept): only paths the stash did not change stay staged;
6938778 says the owner's own conflict "costs one `git diff` per Stop": it is one per such unmerged
index or `CLAUDE.md` (one in its test and in `review-r2/lh5-after.txt`); 98d153a gives commit 45's
cost with a real change as "+60 to +80 ms per Stop": the file of that measurement was overwritten,
and its repeat on a quiet machine measured clean home 27.1 to 29.3 against 27.7 to 30.6 ms (difference -1.5 to +0.9), an uncommitted allow entry 553.3 to 597.4 against 485.6 to 531.5 ms (difference +21.8 to +93.9) (`review-r3/n1-cost-8ab874b.txt`); the
later round-4 measurement of the same code (variant (a) of review NF-1's experiment) is in the N1
row of the technical choices. The bodies of 26a7ea7 and 96bcb8f each name one `git ls-files -u`
(in `repaired()`, and after the landed repair); commit 51 removes both reads (`repair_pop` returns
the refused paths instead). 10d7d25 says that the NF-3, V1-1 and NV-1 tests check the exit its
docstring states; the NF-3 test lands an upgraded home, whose `render-settings land` exits 0, so
only the V1-1 and NV-1 tests do (`result=repair-refused` with the notice).

### Decisions applied

- Owner statement 2026-10-18 / D19: no owner step; the PR has no REQUEST. Merged code reaches a home
  only through his /pull; nothing pulls automatically.
- D1: migrate never writes `GIT_AUTO_PUSH` "1" and names it; a working "1" is dropped (named) when
  settings.json is taken from HEAD; pre-landing sessions push only when the rendered settings say "1";
  legacy hooks that push unless "0" are renamed aside; a restarted daemon gets its own environment,
  never the session's, and one that a pre-landing session started loses that session's
  `GIT_AUTO_PUSH`. The opt-in template stays.
- D3 / D18: no question anywhere; each technical choice below names the experiment that decided it,
  except the code location and the log path, whose rows say that no alternative was tried.
- D4 / S1: the landing exits 0 (an EXIT trap since round 2); a failed or skipped landing is a
  notice (acceptance 16).
- D10: technical choices table below.
- D11 / S3: settings.json stays tracked in clean form; the filter, record and pre-commit hook are
  installed by init's own steps; nothing personal is staged (index clean in every state).
- D12 / S6: messages, logs, notices, tests and commit messages carry key names, counts and revision
  ids only (acceptance 19); the seeded list is local, 0600; the previous settings taken from a stash
  stay in memory (no temporary file).
- D13 / S5: paseo is detected by `module_enabled` as before; a fresh clone is never touched, also
  when it checked out an older revision and came back (acceptance 13, the clone-entry rule).
- D14 / S4: personal-path allows go into the overlay exactly as P7's migration puts them.
- D15: no hook file deleted or unregistered; a daemon is stopped only to be started again with the
  current code; when the new process does not start (review RQ-2: a `git-fswatch.sh` that exits),
  the daemon stays stopped and that Stop's notice says so once ("1 git-fswatch restart(s) failed"),
  as R8 allows ("a restart that fails is a notice, never a retry loop"); an owner's own hooks in an
  LFS repository, and a legacy hook a repository tracks, are left as they are.
- D16 / S7: no history rewrite, no remote ref touched; no code or test deleted.
- Producer-side, no new mutable state: one departure, decided by review NF-1's experiment (D18) and
  recorded here. `<git common dir>/claude-settings.checked` (empty; written only by the landing's
  `touch -r settings.json`, read only by its `-nt` tests) tells the landed fast path that the
  current `settings.json` was already diffed through the filter and holds a real change. Without
  it, (a) diffing at every Stop costs one filter run per Stop while a real change stays (+92 to
  +102 ms in the landing, +132 to +156 ms in the auto_commit phase against d625284: over acceptance
  11's +50 ms); (b) comparing with the index's mtime leaves /pull refused after an index write
  between the CLI's write and the Stop (an owner's commit of another file: `pull.sh rc=1` at every
  later Stop); (c) giving the index `settings.json`'s mtime re-runs the filter at every Stop as soon
  as an entry was recorded in the same second (git's racy test is in whole seconds, and the Stop's
  own `git status` then rewrites the index) and sets the mtime of git's own file. Deleting the
  marker is harmless (one filter run at the next Stop with a real change). The governing decision
  is not met for this file; the owner may overrule it, and the row says how to revert.
- Owner input "also the other repositories": R6 and R8 also act on the repositories under `$HOME`
  (depth 5), counts only.

### Technical choices

| Choice | Experiment and result | Why | How to revert |
|---|---|---|---|
| Trigger: `hooks/auto-commit.sh`, before its repository check | Fact 8: all 83 old registrations exist here; acceptance 1, 3, 4 land from the old session's Stop, 2 and 14 from a post-pull session; P1's coordinator relays the line (acceptance 8) | Registered by both settings forms, runs at every main-session Stop | Remove `hooks/auto-commit.sh:20-24` and the `notice;` calls |
| Code location: `scripts/install/land` (bash) + `render-settings land` (python) | No alternative was built and measured; what the rows below show is that the python half reuses `parse`, `merge`, `diff`, `cmd_migrate` and `machine_form` (acceptance 4: the same `cmd_migrate` from both init and the landing) and the shell half needs `flock`, `/proc` and process control: an untested choice (no smaller or single-language design was tried) | Settings work reuses parse/merge/diff/migrate; process, lock and daemon work is shell | Delete `land`; drop the subcommand |
| Reuse of init: `bootstrap --steps 3,4,5` (or `5`, or `3,4` when step 5 cannot install); step 6 not run | Acceptance 11: a stale pre-commit refreshed by `steps 5 done` alone; `test_global_hooks_path_gives_one_notice_then_counts_as_landed` | No second copy of any step; step 5's body intact for P8's row 12. Step 6 writes nothing (a check and a chmod of files git already tracks executable) and its python half needs the venv | Remove `--steps` and its wrappers |
| Rev detection: the newest revision of `<git dir>/logs/HEAD` (each entry's new value, then its old one; an all-zero old value skipped), then `ORIG_HEAD`, whose `.gitattributes` lacks the filter (one `git grep` over them); a stopped merge's `MERGE_HEAD` also counts as the new tip; a reflog whose oldest entry is a clone (`clone: ...`) of a filter revision is a fresh clone, left to init | `test_rev_detection_survives_an_overwritten_orig_head` (ORIG_HEAD rewritten, reflog deleted, fresh clone); the matrix's merge x local-commit row found the `MERGE_HEAD` case (`test_s4_stopped_merge_on_pre_p7_head_gets_the_notice`); `test_a_clone_made_after_p7_that_looked_at_history_is_not_landed` (without the clone rule: state `upgraded`, landed with paseo on from the old revision; `fix/evidence/c12-before.txt`); review LH-1: with the new values alone and `ORIG_HEAD` only without a reflog, a home whose reflog gc had emptied before a fast-forward pull stayed `none` on every pull path (`r3/evidence/expired-prevhead.txt`: `assert-landed: 3/9`, legacy hook active); with the old values and `ORIG_HEAD` it lands (`expired-after.txt`: 9/9 on merge, /pull and fswatch; `test_a_home_whose_reflog_expired_before_the_pull_is_upgraded`, with `ORIG_HEAD` deleted for its second check) | One process for any reflog length; D13 | Drop the clone-entry test in `pre_pull_rev`; read `git log -g` again |
| Previous settings: S3 the pull's stash (in memory, no file), looked for only while a path is unmerged; S1/S2 rev's file + the working entries HEAD's clean form lacks | Acceptance 1 (live model kept, from the stash), 2 (live allow kept); `test_an_older_entry_at_rev_is_not_the_pulls_once_the_pop_merged` (a merged pop drops its own entry; taking an older entry at rev instead lost the live allow: mutation `stash-without-unmerged`) | The overlay holds everything the working file adds; no personal value written to a temporary file | Take the previous settings from rev's file only (`previous_settings`) |
| settings.json from HEAD: as the last act of the settings step, by any run, while no render has written the record and settings.json is not unmerged; the overlay's missing entries are dropped and named (key paths) | Review round 1: with the checkout tied to the run that migrated, a landing killed after the migration, or one CLI write between that checkout and init step 3's render, made the render refuse at every later Stop (`failed-steps-3,4,5`); `test_a_landing_cut_short_after_the_migration_completes` (push-one) and `test_a_cli_write_between_the_settings_step_and_the_render_does_not_wedge` (S1, S2) fail without it (`fix/evidence/c7-before.txt`); sandbox `window`: Stop 1 lands with `dropped from settings.json, as the overlay does not hold them: permissions.allow: 1 entry`; `wedge` still keeps an entry the CLI wrote before the migration | The overlay that exists is never rewritten (DO NOT), so an entry the CLI writes after the migration has nowhere to go; dropping it, named, ends a wedge no human would end (D19); D1 drops the "1" | Take settings.json from HEAD only in the run that migrated (`if migrated and changed` in `land()`) |
| A landed home's repair names the live entries it drops: the stash's `settings.json` against its base, then against HEAD's (`diff`, `describe`: key paths and counts) | Review LH-7: upstream and the CLI each append an allow entry, the pop conflicts; round 2's repair took upstream's side and named nothing (`verify-r2/evidence/LH7.txt`); this head's notice adds `dropped from settings.json, as the overlay does not hold them: permissions.allow: 1 entry (in the stash entry)` and the log `settings.json taken from HEAD; dropped: permissions.allow: 1 entry` (`review-r2/lh7-after.txt`); `test_a_landed_repair_names_the_live_entries_it_drops` | The same wording as the upgraded home's `from_head`; the stash entry keeps the values | Drop the `docs`/`lost` lines in `land()` |
| Stash match: newest entry whose first parent is rev and whose settings.json differs from rev's; for the doc-sync exception, without one, the newest entry at rev | `test_stash_is_found_by_content_not_by_message` (a newer unrelated entry at rev is skipped; mutation fails it); `test_doc_sync_conflicts_on_an_upgraded_home_whose_pull_left_settings_alone` (without the fallback both doc-sync paths stayed unmerged until the next Stop; `fix/evidence/c8-before.txt`) | Messages differ by pull path | Drop the settings.json comparison and the fallback (`pull_stash`): newest entry at rev |
| Unstaging: `git --literal-pathspecs reset -q HEAD --pathspec-from-file=- --pathspec-file-nul`, for the staged paths whose index blob equals the stash's or that the stash changed and the pop merged (index equal to the working file), never with an empty list; on an upgraded home whenever the pull's entry was found, on a landed home once a path was taken from upstream | `work/evidence/experiments.txt`: after a conflicted pop `M  o.txt UU s.txt`, an empty pathspec file resets the whole index (` M o.txt  M s.txt`); `test_other_unmerged_paths_stay_and_an_empty_unstage_list_resets_nothing`, `test_s3_...` (a path staged later stays staged, `a*b.txt` unstaged literally), `test_a_pop_conflicting_only_on_another_file_still_unstages_what_it_staged`, `test_a_path_the_pop_merged_and_staged_is_unstaged_too` (without the merged rule `M  multi.txt` stayed staged; `fix/evidence/c9-before.txt`) | Exactly what the pop staged, nothing else (R2's goal: the index equal to HEAD for those paths) | Leave the pop's staged paths staged (drop the `git reset` in `repair_pop`) |
| Lock: `flock -n` on `<git common dir>/claude-landing.lock` (fd 9; python `fcntl` fallback), state re-read under the lock; a restarted daemon gets fd 9 closed | Acceptance 12 (one `result=landed`, one `result=skipped`); `test_lock_taken_lands_nothing`; the daemon test fails without `9>&-` (mutation `no-fd9-close`) | No state beyond a lock file | Remove the lock block (`land:205-211`) |
| Notice: one line, auto-commit's last stdout line as `systemMessage`, joined after the refused-snapshot notice; `"` and `\` removed; the repair notice and the landing's own word conflicted paths the same way (`repaired()`) | Acceptance 8 shows the joined line relayed by P1's coordinator; `test_auto_commit_relays_the_notice_as_its_last_line`; `test_doc_sync_only_conflicts_take_upstreams_side` checks the whole repair notice (without `repaired()` it lacked "the stash entry kept" and the left count; `fix/evidence/c11-before.txt`) | The coordinator parses only the last line of a passing phase | Print nothing (`land` without the `printf` in `finish`; the log keeps what was done) |
| Log: `logs/landing.log`, append-only; python writes its own lines; bootstrap's output with the home path replaced by `<home>` and `$HOME/` by `~/` | No alternative was compared; the runs show only that the chosen log holds no value: every acceptance run, `str(home) not in log` in the end-to-end test, acceptance 1-4 `seeded-values-in-output=0` | One log, no value (render prints key paths and counts only) | Delete the file |
| Seeding filters: split on `\|`, `,`, whitespace; trim; >= 4 characters; drop clean-form env values and their words, HEAD's code defaults, the shipped hard-ban default, clean-form permission paths; drop the origin URL's owner (case-insensitive); drop a value that HEAD's tracked files hold in 100 or more lines (one `git grep -F -f -`, the values on its stdin; the log counts what it left out); de-duplicate; hard bans: plain words only; trailer: the e-mail; paseo model: the part after `@` (none without `@`); paths: `//path` read as `/path`, at least two levels deep, outside the harness home and outside the harness home that rev's hook commands name for a script rev tracks (one `git ls-tree` of rev) | The previous home's paths (review F3): in the `/home/alice` layout 1b58fa0a seeded 36 values (round 2's head 37), 15 of them `/root/.claude/scripts/...` permission paths (harness scripts), and a README line naming one was refused (`verify-r2/evidence/F3.txt`, `F3b.txt`); this head seeds 21, the root layout's count, and no such path (`review-r2/f3-after.txt`, `f3b-after.txt`); `test_seeding_sources_filters_and_no_value_printed` (its old home `/opt/demo/.claude`) fails without it. The 100-line rule (review LH-2, `r3/exp/lh2-stats.txt`, `r3/evidence/common-*.txt`, `occurrences.txt`; counts only): of round 2's 22 seeded values, one is in 595 tracked lines (31 files) at 1962cb6 and the other 21 in 0 to 47 lines each; PR #6's head keeps that one in 532 lines (23 files) and none of the other 21; 29 of the last 300 first-parent commits up to fe7700c8 added a line holding it; seeded (round 2's kit), one README line holding it refuses the whole checkpoint snapshot (`refs/checkpoints/master moved: no`); left out (this head), the same line is checkpointed (`moved: yes`) while a line holding a seeded value is still refused; 100 lies between 47 and 532; `test_a_value_the_tracked_tree_holds_in_100_lines_is_not_seeded` (100 lines: left out, 99: seeded). Other filters: acceptance 10 (exact stand-in list; `demo-owner`, `abc`, `xyz`, `session-recovery`, `/var/tmp/claude-scratch` dropped); `test_seeding_sources_filters_and_no_value_printed`, `test_seeding_never_rewrites_a_list_that_has_lines` (a comment-only list is now kept as it is; it was appended to before: `fix/evidence/c13-before.txt`); mutations `no-model-at`, `no-slashslash`, `seed-rewrites-list` fail them | Seed what the machine holds, never the public defaults or the tree's own vocabulary; R5: never rewrite a list that has lines | Remove `seed_literals` (the list stays as init leaves it); for the 100-line rule, drop `common`; for the previous home, drop the `homes \|=` lines |
| Which list counts as "empty" for R5 (a choice, not R5's wording: R5 says "absent or empty" and the DO NOT says "never rewrite a non-empty list"): absent, 0 bytes, or blank lines only; a list with any other line, a `#` comment included, is kept | `r3/exp/empty/result.txt`: this head's private-literal rule (`scripts/check-public-core.sh --private-literals`, which the pre-commit hook and the snapshot run) on a staged stand-in line gives `SKIP: private-literal rule` for an absent list, 0 bytes, blank lines only and a comment-only list, and `FAIL` (rc 1) for a list holding the stand-in; init step 4 creates the list with `: > "$LITERALS"` (0 bytes); `test_seeding_never_rewrites_a_list_that_has_lines` | A blank-only list lists nothing and holds nothing a person wrote that seeding could lose; a comment-only list lists nothing either, but a person wrote it, so it is kept | Seed only an absent or 0-byte list (`data.strip()` -> `data`) |
| Legacy hooks: `post-commit` files containing `GIT_AUTO_PUSH:-1` in `hooks/`, `keystone-hooks/preserved/` and the core.hooksPath directory, renamed to `<name>.auto-push-disabled`, except one that its repository tracks (`git ls-files --error-unmatch`), which is left and counted; where one carried the LFS step, git-lfs's own post-commit (from `git -c core.hooksPath=<scratch dir> lfs update`) copied to the renamed hook's path | Acceptance 9: `refs/backups` 0 (d625284: 1), keystone dispatcher left, opt-in template unchanged; `fix/evidence/lfs-update.txt` (git-lfs 3.4.1): plain `git lfs update` stops at the first hook that exists (a custom pre-push: post-commit not installed, rc 2); `--force` overwrote an owner's pre-push and post-merge (review LH-4); `lfs-update2.txt`: the scratch-dir route installs post-commit, keeps three custom hooks, global config 0 bytes; `test_the_lfs_post_commit_is_restored_and_no_other_hook_is_touched` fails with `--force` (`fix/evidence/c6-before.txt`); review LH-3: a tracked `.githooks/post-commit` renamed aside showed as deleted in that repository and its next `git commit -a` recorded the deletion; `test_a_legacy_hook_a_repository_tracks_is_left_and_counted` (that repository's status stays clean) fails on round 2's code | Reversible, keeps the content; "do not delete an installed hook"; a tracked hook is that repository's content, not an installed copy | `mv <name>.auto-push-disabled <name>`; drop the LFS copy (`land:74-79`) |
| Other repositories ("also"): every `.git` directory under `$HOME` to depth 5 (`find`, cut after 5 s; the loop over them, after 8 s); a cut scan is logged (`scan=timed-out`) and named in the notice | End-to-end test (a repository under the test's `$HOME` renamed, LFS restored); acceptance 9 (a scratch repository's opt-in template untouched); `test_a_timed_out_repository_scan_is_logged_and_named` (a stub `find` that outlives the limit; without the change the notice said nothing of the cut scan and the log had no mark of it: `fix/evidence/c5-timed-out-before.txt`) | The places P0's REQUEST searched; R1's bound | Drop the `find` from `legacy_hooks` |
| Claude-process variable: `CLAUDECODE` or `CLAUDE_PROJECT_DIR` set, `CLAUDE_HOME` absent; helper `settings_env()` + `claude_home.py env` (shell assignments for `eval`) | `work/evidence/experiments.txt`: in the local CLI binary the string `CLAUDECODE:"1"` occurs 5 times, in the environment objects it builds for hook and Bash tool processes, and `CLAUDE_PROJECT_DIR` 58 times; this session's own tool process has `CLAUDECODE=1`; acceptance 6 and 7; R7 tests. The official hooks documentation was not read (the earlier rounds had no network): UNVERIFIED there | Either variable marks a hook or tool process | Remove the R7 lines |
| `GIT_AUTO_PUSH` "1" in the check: an `[info]` line, not a failure | `r3/exp/check-line.txt`, a landed sandbox home whose overlay sets `GIT_AUTO_PUSH` "1": as an `[info]` line, `check rc=0` and `scripts/doctor` rc 0; as a failure (a copy of `render-settings` with that line made a `[FAIL]`), `check rc=1` and `scripts/doctor` rc 1 (its settings step fails); acceptance 5 (rc 0 with and without the key) | D1 lets a human opt in on purpose: a failure would make doctor red on every home whose owner chose push | Make it `_ok(..., False)` |
| Pre-landing bash-safety knobs read only while the rendered `settings.json` holds `"CLAUDE_HOME"` (`grep -qs` before the python helper, `pretool-bash-safety.sh:8-14`) | `r3/exp/precond/result.txt`: on a home whose rendered settings lack `CLAUDE_HOME` (unlanded: the tracked clean form), a Claude Code process without `CLAUDE_HOME`, PreToolUse Bash `ls`, 3 x 20 runs: with the precondition medians 515.7, 506.9, 525.3 ms, without it 561.4, 549.6, 551.8 ms (+26 to +46 ms per agent Bash call), and the helper would take 0 keys from that file; on a landed home the knobs apply (acceptance 7: `BLOCK(exit2)` for the stand-in hard ban; review RQ-6's replay: rc 2 with `CLAUDE_HOME` in the rendered settings, rc 0 without) | A python process per Bash call buys nothing where the rendered settings carry no overlay | Drop the `grep -qs` clause |
| Daemon candidates: one builtin read of each `/proc/<pid>/cmdline` (a bash or sh process whose argv[1] ends in `git-fswatch.sh`), started at or before the newest mtime of `git-fswatch.sh` / `checkpoint-core.sh`, both in centiseconds (the boot time as `EPOCHREALTIME` minus `/proc/uptime`, the mtimes from `stat -c '%Y %y'`; one `stat`, one `getconf` only when such a process exists) | review LH-4: with whole seconds (`/proc/stat`'s `btime` is truncated) a current daemon started 0.3 s after its code was written was restarted, and a just-restarted one once more at the next Stop (`verify-r2/evidence/LH4.txt`); in centiseconds neither is (`review-r2/lh4-after.txt`), and `test_a_daemon_started_just_after_its_code_was_written_is_current` fails with whole seconds (3 of 3) and passes (5 of 5); `fix/evidence/scan-scale.txt`: 1.7 ms against `pgrep -f`'s 7.7 ms at 89 processes, 14.6 against 35.7 at 589, 28.4 against 50.9 at 1089 (`pgrep-scale.txt`: `pgrep -f` alone grows 45 µs per process); `test_a_zombie_named_like_the_daemon_leaves_the_landing_at_exit_0` (`pgrep` listed a zombie whose empty cmdline stopped the old code with exit 1: `fix/evidence/c1-before.txt`) | Cheap enough for every Stop of a landed home | Use `pgrep -f 'git-fswatch\.sh'` again |
| Daemon restart: in its git work = a git child, or an `index.lock` younger than 60 s (`r3/exp/lock/result.txt`: in a clone of this branch, 912 tracked files, the git calls of git-fswatch's sync and `safe_pull` (add, commit, stash push, pull --rebase, stash pop, status) held `index.lock` for at most 64 ms per run, 3 rounds; a lock no git holds stays until removed and makes `git add` fail with "File exists"; 60 s is about 900 times the longest hold, and a lock older than that is one a git that is gone left behind); a restart whose new process does not start leaves the daemon stopped, with one failure notice (review RQ-2); only the harness home's own busy daemon holds the landing, a busy one elsewhere is counted and left; a rebase or merge stopped in its repository: left; a daemon whose repository is gone: skipped; systemd unit (from its cgroup): `systemctl [--user] restart` (UNVERIFIED: no systemd in this container, `/run/systemd/system` absent, and no test covers it); else TERM the tree (KILL after 3 s) and start detached with `env -i`, its `/proc` environ (without `GIT_AUTO_PUSH` when it has `CLAUDECODE` or `CLAUDE_PROJECT_DIR` and no `CLAUDE_HOME`) and the absolute script and watch path | Acceptance 15 (old pid gone, new daemon with `FSWATCH_DEBOUNCE=7`, no `GIT_AUTO_PUSH`); `busy` run (Stop 1 waits with `overlay: absent  filter: unset`, Stop 2 lands and restarts the home's daemon, the toy repository's daemon left with its stopped rebase); `test_stale_daemon_restarts_with_its_own_env_and_without_the_lock` (mutation `daemon-after-settings` fails it); `test_a_busy_daemon_in_another_repository_does_not_hold_the_landing` (both cases waited before: `c3-before.txt`); `test_a_daemon_a_session_started_loses_that_sessions_push_switch` (the two session cases kept `GIT_AUTO_PUSH=1` before: `c2-before.txt`; review LH-2: such a daemon's `safe_push` pushed) | A daemon keeps the functions it loaded; killing it mid-pull would leave a stash or a stopped rebase; another repository's daemon, or a lock a dead git left, must not keep the harness unlanded | Remove `restart_daemons` |
| Landed-home retry: at every Stop the candidate scan; when a stale candidate exists, `restart_daemons landed` under the lock, which says (notice, log line) only what it restarted or failed to restart | `test_a_daemon_left_running_is_restarted_at_a_later_turn_end` and the retry half of the busy-daemon test fail without it (`c4-before.txt`); sandbox `busy` Stop 3: `Harness landing: 1 stale git-fswatch daemon(s) restarted.` once the toy repository's rebase is gone, Stop 4: `notices 0, log lines added: 0`; cost row below | R8: "try again at the next trigger" | Drop `stale` from the landed fast path (`land:203`) and `land:214` |
| A landed home's `settings.json` stat (review N1, NF-1): when `git diff-files` finds the entry stat-dirty and `settings.json`'s mtime differs from that of `<git common dir>/claude-settings.checked` (absent: differs), `git diff --quiet` through the filter; no change: `git update-index --cacheinfo` (the same mode and blob of an unflagged stage-0 entry) and `git update-index -q --refresh`, as render-settings' `refresh_index`; a change: the marker takes the file's mtime (`touch -r`) and nothing is re-recorded | `n1`: after a CLI `model` write and a Stop, `pull.sh rc=0` and `safe_pull rc=0` with HEAD at the upstream commit and the CLI's `model` kept (`review-r4/n1-after.txt` on 26a7ea7a, `n1-after.txt` on 98d153ad); 1d10ae00 and d625284 after P7's manual init: `pull.sh rc=1` (`cannot pull with rebase: You have unstaged changes`) and `safe_pull rc=0` with HEAD behind, after the Stop as before it (`review-r3/prevhead/n1-after.txt`, `n1-before.txt`). Review NF-1's experiment (`review-r4/`; kits of 98d153ad with each variant's `land`, interleaved, each in its own PID namespace; the landed scenario-3 home clean, after a CLI `model` write, and with an uncommitted allow entry, at the first Stop after the write and at later ones): the landing alone against the branch before N1's code (1d10ae00), 3 rounds of 10: clean +0.2 to +3.7 ms for every variant; first Stop after a `model` write +173 to +202 ms (two filter runs, then the stat is clean) and after an allow entry +84 to +99 ms (one filter run), for every variant; later Stops with the allow entry: (a) every Stop +92.4 to +102.1 ms, the marker +2.9 to +4.5, (b) +1.9 to +3.9, (c) +2.0 to +2.9, the marker with the different-mtime test (commit 47's `land`) +3.4 to +4.3 (`nf1-land-only-summary.txt`). The auto_commit phase against d625284, 4 rounds of 10: clean +11.4 to +20.8 ms for every variant (commit 47's `land` +11.4 to +17.0); after a `model` write 34 to 118 ms below d625284, whose every Stop then runs the checkpoint path (later Stops 261 to 307 ms below); with the allow entry, later Stops: (a) +131.9 to +155.8, the marker +30.2 to +101.3, (b) +52.3 to +96.6, (c) +30.9 to +69.3, commit 47's `land` +5.6 to +81.2 (`nf1-cost-summary.txt`); the branch before N1's code already measures +25.3 to +82.5 there (`nf1-cost-summary-pre.txt`, under "Out of scope, found"). Gaps (`nf1-hole-kit.txt` in the kits, `nf1-explore.txt` in test homes): an index write between the CLI's `model` write and the Stop (an owner's commit of another file, a staged new file, a plain index write) leaves (b) stat-dirty after the Stop and `pull.sh rc=1`, at every later Stop too; (c) misses it when that write falls in the same coarse timestamp as the CLI's (the plain index write right after it, 1 of 3 cases); the marker, (a) and 26a7ea7a (its own kit) pull. The clean file put back with an older mtime after a real change was diffed leaves the marker (98d153ad) and (b) stuck (`pull.sh rc=1`); (a), (c) and 26a7ea7a (its own kit) pull. Why (c) costs a filter run per Stop: git 2.43 here counts an entry recorded in the same second as the index's mtime as racy, so after (c) sets the index's mtime back the Stop's `git status` rewrites the index, whose new mtime differs again: the filter ran at 4 of 4 Stops, against 1 of 4 for (b) (`nf1-variant-c-rewrite.txt`); setting the index's mtime back only makes git compare more entries, never trust one more (`nf1-racy-demo.txt`). `test_a_cli_write_of_its_own_key_does_not_stop_the_pulls_after_a_stop` (/pull and `safe_pull`), `test_a_real_change_is_left_as_it_is_and_only_a_clean_one_is_re_recorded` (a later index write runs no diff), `test_a_cli_write_is_re_recorded_whatever_wrote_the_index_since` (the index-written case guards against (b); the file-back case fails on 98d153ad's code) | Git trusts a size change without running the clean filter (`refresh_index`'s docstring); render itself refuses a working file with entries the overlay does not explain; clearing the cached stat of a real change instead would cost every later `git status` a filter run; no variant without a file of its own keeps N1 fixed within +50 ms (above) | Remove `land:190-202` and delete the marker; for variant (a), drop the marker test and the `touch -r` |
| Time budget: the scan stops after 5 s; the loop over the repositories it found takes the harness home's own first and no other one after 8 s (logged and named as a cut scan); a restart (up to 4.2 s) starts only while the landing is under 8 s; the rest are counted (`later=N`) and restarted by the landed-home retry | `test_daemon_restarts_stop_at_the_time_budget_and_go_on_at_the_next_turn_end`: three daemons that need the KILL took 20.0 s in one landing before (`c5-before.txt`), 9.4 s after (2 restarted, 1 at the next Stop, 4.5 s; `fix/evidence/landing-duration.txt`); review RQ-4: 3500 empty repositories under `$HOME` made a 16.26 s landing on round 2's head (`verify-r2/evidence/RQ4-3500.txt`), 8.22 s on this head with `scan=timed-out` (`review-r2/rq4-after.txt`); `test_the_loop_over_the_repositories_found_keeps_to_the_time_bound` (5 repositories at 3 s each: 15.8 s and nothing cut before, cut at 8 s after) | R1: target under 15 s | Remove the `$SECONDS` checks (`land:63`, `land:141`) |
| Migrate leaves out hooks upstream unregistered (a hook whose harness script the previous revision tracks) | d625284's migrate puts P1's retired `stop-completion-gate.py` Stop entry back into the overlay (acceptance 3 before: `upstream hook command (Stop) removed x1` against `x2` after); `test_migrate_skips_hooks_upstream_unregistered`; mutation `keep-retired-hooks` | The script was public at that revision; once P10 deletes the stub, python3 on the missing file exits 2 at every Stop | Remove `_tracked_hook` |
| Landed test compares only the hooks whose second line is `# claude-harness <name> (installed by scripts/bootstrap)` | End-to-end test: an opt-in template without the line keeps the home landed (mutation `no-install-marker` fails it) | A template step 5 does not install must not re-run step 5 at every Stop | Compare every non-doc file |
| Doc-sync exception: an unmerged `INDEX.md` / `CLAUDE.md` whose stash change against the stash's base is only `*Last updated: ...*` / `> Last updated: ...` lines takes HEAD's side, or `git rm` when upstream deleted it (`DU`); on a landed home `--repair` runs only while the stash reflog is non-empty and `settings.json` is unmerged, or an index or `CLAUDE.md` whose change in the newest stash entry is doc-sync's date lines alone (one `git diff` of that path, in the landed fast path) | `ds` run: d625284 leaves `DU`/`UU` and the next /pull fails with `needs merge`; this branch resolves both (`2 doc-sync`), stash kept, next /pull `rc=0`; `test_doc_sync_only_conflicts_take_upstreams_side` (a file with an owner line stays unmerged); review LH-5: with the owner's own `CLAUDE.md` conflict every Stop ran the repair, 100 to 120 ms and two log lines (`verify-r2/evidence/LH5.txt`), now 26 to 30 ms and none (`review-r2/lh5-after.txt`); `test_an_owners_own_doc_conflict_runs_no_repair_at_each_stop` | The exact lines doc-sync rewrites; a conflict that is the owner's own is not the repair's | Remove the INDEX/CLAUDE branch of `repair_pop`; for the gate, match the unmerged path names alone again |
| S4 also covers a stopped cherry-pick, revert or squash merge (`SQUASH_MSG`: `git merge --squash` stops without a `MERGE_HEAD`) | Same notice path (`test_s4_*`; mutation `no-s4-check`); `test_a_stopped_squash_merge_is_an_integration_in_progress` (before, the landed home's repair took settings.json from HEAD under a stopped squash: `c10-before.txt`) | They hold the owner's work | Drop the three entries (`land:216-217`) |
| /pull's stash (routed by PR #6's review): `STASHED=1` only when `refs/stash` changed across `git stash push` (`git rev-parse -q --verify refs/stash` before and after) | `pullsh`: d625284's `hooks/pull.sh`, an untracked file only and an older entry, says `Stashed as: stash@{0}`, pops the older entry and applies its change (`pullsh-before.txt`); this head's says `Nothing was stashed`, keeps the entry, rc 0, and on an S3 home the landing left keeps the landing's entry with `settings.json` unchanged (`pullsh-after.txt`); `test_pull_sh_pops_only_an_entry_its_own_push_made` (before: rc 1, "No stash entries found", and the kept entry popped into a conflict) | The only change that tells "saved nothing" from "saved" without changing what /pull stashes (`-u` would also stash untracked files) | Set `STASHED=1` after the push again (`hooks/pull.sh:34-42`) |
| fswatch's pop (routed by PR #6's review): `${PIPESTATUS[0]}` of `git stash pop \| tee` | `fswatchpop`: d625284's `safe_pull` logs `Stashed changes restored` and returns 0 with `UU README.md` (`fswatchpop-before.txt`); this head's takes the failure branch, `MANUAL INTERVENTION REQUIRED`, rc 1, the entry kept (`fswatchpop-after.txt`); `test_fswatch_safe_pull_reports_a_failed_pop_as_failed` | The pop alone was routed; `set -o pipefail` would change the fetch, stash and pull branches too | `if git stash pop 2>&1 \| tee -a "$LOG_FILE"; then` again (`hooks/git-fswatch.sh:223-224`) |
| fswatch's stash push (review NF-2): `stashed=1` only when `refs/stash` changed across `git stash push`, "Nothing was stashed" otherwise, as `hooks/pull.sh` does | `review-r4/nf2-fswatch-untracked.txt` (a test repository, upstream one commit ahead, an untracked file only): d625284's `safe_pull` says `No stash entries found` yet `Stashed changes restored`, rc 0, and with an older entry pops it and applies its change; 98d153ad's says `MANUAL INTERVENTION REQUIRED`, rc 1, or pops the older entry; this head's says `Nothing was stashed`, rc 0, the entry kept; `test_fswatch_safe_pull_pops_only_an_entry_its_own_push_made` (both cases fail before) | The comparison /pull already makes (commit 42); `git stash push -u` would stash the untracked files too, a change of what fswatch stashes | `stashed=1` after the push again (`hooks/git-fswatch.sh:197-209`) |
| Notice wording for a path git refused to repair (reviews NF-3, NV-1): `repair_pop` returns the paths of its repair (`settings.json`, and an `INDEX.md` or `CLAUDE.md` of the doc-sync exception) whose checkout or rm git refused, and `repaired()` names them apart, "settings.json still conflicted: git refused its repair, tried again at the next turn end" for `settings.json` alone, "CLAUDE.md, settings.json still conflicted: ..." for two, counting only the other unmerged paths (no git call of its own since commit 51; before, one `git ls-files -u`); on a landed home `render-settings land --repair` gives these parts while such a path stays unmerged as well (before commit 50, only once a path was taken from upstream) and then exits 1, which `land` logs as `result=repair-refused` instead of `result=repaired` (review V1-1; since commit 51 from that exit status, in place of commit 50's `git ls-files -u -- settings.json` after the landed repair). Since commit 53 a control character in a named path is named as `?`, so the notice stays one line and `auto-commit.sh`'s JSON line parses (review NV1-2-1). A repair run that fails outright (an exception) exits 1 as well, with its failed step `settings` on stdout: since commit 54 `land` gives "the settings repair failed (see logs/landing.log); it runs again at the next turn end" for it and logs `result=repair-failed` after its `land: failed: <type>` line (review NV1-2-2; on 10d7d254 the notice was "Harness landing: settings." and the result `repair-refused`); at commit 50 such a run was logged `repair-refused` as well while `settings.json` was unmerged after it, from `git ls-files -u -- settings.json` (the verifier's `verify-nv1-2/ev/crash-before.txt`, 96bcb8f2), and `repaired` only when it was not (read from the code, not run), and before commit 50 always `repaired` (this row said "before commit 51, `repaired`", which held only when `settings.json` was not among the unmerged paths). Since commit 55 the replaced characters include `\x80`-`\x9f`, U+2028 and U+2029, at which the coordinator's `str.splitlines()` breaks the line as well (review NVF-1), and since commit 56 a repair run that exits non-zero with nothing on stdout (a `render-settings` that does not compile, or an exception that escapes `cmd_land`'s `try`) is `repair-failed` with the same sentence (review NVF-2; on 760f06e7 `repair-refused` and no notice) | `review-r4/nf3-notice.txt`: with `index.lock` held, an upgraded S3 home with an owner's unmerged file said `2 other conflicted path(s) left as they are`; now the `settings.json` part and `1 other conflicted path(s)`; without the lock the next Stop repairs it (both before and after); `test_a_settings_json_git_refused_to_repair_is_named_apart_from_other_paths`. Review V1-1 (`review-v1/v1-1-*.txt`): on a landed home with the lock held, 26a7ea7a gave no landing notice and logged `result=repaired`, 96bcb8f2 and this head give the notice and log `result=repair-refused`; without the lock both repair the file at the next Stop (`result=repaired`); `test_a_landed_settings_json_git_refused_to_repair_is_named_and_logged_apart`. Review NV-1 (`review-nv1/nv1-lock-*.txt`): with the lock held, 96bcb8f2 gave no notice and logged `result=repaired` for doc-sync's `CLAUDE.md` alone, and counted it as `1 other conflicted path(s) left as they are` next to `settings.json`; this head names `CLAUDE.md` (and `CLAUDE.md, settings.json`) and logs `result=repair-refused`; without the lock both heads repair both at the next Stop; `test_a_doc_sync_file_git_refused_to_repair_is_named_and_logged_apart` (both cases). Review NV1-2 (`review-nv12/`): with the lock held, a tab or a newline in a refused doc-sync directory's name left that Stop without any relayed notice on 10d7d254, and this head names it with `?` (`oddpath-tab-*.txt`, `oddpath-newline-*.txt`); a failed run's notice and result before and after (`crash-*.txt`); `test_a_refused_path_with_a_control_character_keeps_the_notice_one_line`, `test_a_landed_repair_that_fails_outright_says_so_and_is_logged_apart`. Review NVF (`review-nvf/`): with the lock held, U+2028, U+0085 or U+2029 in a refused doc-sync directory's name left that Stop without any relayed notice on 760f06e7, and this head names it with `?` (`odd-ls-*.txt`, `odd-nel-*.txt`, `odd-ps-CLAUDE-*.txt`); a `render-settings` that does not compile gave no notice and `repair-refused` on 760f06e7, the sentence and `repair-failed` on this head (`crash-syntax-*.txt`); the U+2028 and U+0085 cases of the first test, `test_a_landed_repair_whose_render_settings_does_not_compile_says_it_failed` | The next Stop repairs these paths (the landed gate and the upgraded landing both run again), so "left as they are" was false for them, and so were silence and `result=repaired` while a file holds conflict markers; the paths come from the one place that ran the checkout or rm, so neither half reads the index again | `repaired(res)` with the single count again; for V1-1, `if res[0]` in the repair branch of `land()` and `finish repaired` in `land`; for NV-1, revert commit 51 (commit 50's `settings.json`-only form); for NV1-2-1, the `re.sub` in `repaired()` (commit 53); for NV1-2-2, the `[ "$out" != settings ]` mapping in `land` (commit 54); for NVF-1 and NVF-2, revert commits 55 and 56 (commit 53's class, commit 54's mapping) |

### Test evidence

Acceptance tests (after = this branch's kit at 98d153ad, `work/evidence/*-after.txt`, and for
acceptance 11 at 921b5128, `work/evidence/review-nv1/`, and for acceptance 17 and 19 at this
head, 1071ad39, `work/evidence/review-nvf/` (760f06e7's runs in `work/evidence/review-nv12/`,
10d7d254's in `work/evidence/review-nv1v/`,
96bcb8f2's in
`work/evidence/review-v1/`, 26a7ea7a's in `work/evidence/review-r4/`); before = d625284's kit,
`work/evidence/*-before.txt`, and for acceptance 11 on 921b5128 a kit rebuilt from d625284,
`review-nv1/11-before.txt`). Commits 47-51 change nothing the other scenarios run beyond `land`'s
landed fast path, `safe_pull`, `repaired()`, which also words the upgraded landing's repair notice,
and the end of a landed home's repair (the texts of both, and that log result, differ only while a
path git refused to repair is still unmerged after the repair, or, for the log result, when the
repair run fails outright), and commit 52 changes a docstring only; commits 53 and 54, and 55
and 56 after them, change only that notice text where a refused path's name holds a control or
line-break character, and the notice and log result of a landed repair run that fails outright;
acceptance 1-10 and 12-16 were not run again on 26a7ea7a, 96bcb8f2, 921b5128, 10d7d254, 760f06e7 or
this head, nor acceptance 11 on 10d7d254, 760f06e7 or this head (the landed fast path it measures is
921b5128's on all three). The
full "after"
outputs follow the table.

| # | Result | Key output, after (this branch) | Before (d625284) | Evidence |
|---|---|---|---|---|
| 1 | pass | fswatch pull: `CONFLICT (content): Merge conflict in settings.json`, `Stashed changes restored`, `safe_pull rc=0`, `UU settings.json`; old-session Stop: all nine lines as required, notice `1 file(s) a pull left conflicted taken from upstream (0 doc-sync), 0 staged path(s) unstaged, the stash entry kept`, `stash entries: 1 (kept)` | `UU settings.json` after the Stop, no overlay | `1-after.txt`, `1-before.txt` |
| 2 | pass | /pull `rc=0`, ` M settings.json`; post-pull Stop: nine lines; `stash entries: 0` | no overlay, `filter: unset` | `2-*.txt` |
| 3 | pass | merge pull; nine lines; `semantic diff vs the live file: only the intended differences` (env added by the overlay x13, module hook commands x3, path form only: hook commands x118 out / x115 in, permissions.allow entries x38 in; upstream Stop changes, added x1 / removed x2: P1's coordinator timeout and retired gate; the same line as round 1's, md5 equal) | no overlay; after P7's manual init the same diff but the retired gate migrated back (`removed x1`) and `legacy post-commit hooks active: 1` | `3-*.txt` |
| 4 | pass | nine lines; semantic diff adds `upstream env.GIT_AUTO_PUSH (D1: 1 -> 0)`; notice `GIT_AUTO_PUSH not migrated: automatic push is opt-in`; migrate from 09ab15bc: `not migrated: GIT_AUTO_PUSH`, `overlay env GIT_AUTO_PUSH: absent` | migrate writes `overlay env GIT_AUTO_PUSH: '1'` | `4-*.txt` |
| 5 | pass | overlay "1": `[info] env.GIT_AUTO_PUSH is "1" in settings.machine.json: automatic pushes are on`, `check rc=0`; without the key: no such line, `rc=0` | no line in either case | `5-*.txt` |
| 6 | pass | `checkpoint refs on origin after 6 s: 0`; positive control `after 1 s: 1`; non-Claude control `checkpoint refs on origin: 1` | `after 6 s: 1` | `6-*.txt` |
| 7 | pass | `BLOCK(exit2)`: `hard-banned script 'demo-recovery' is PERMANENTLY FORBIDDEN`; `test_subagent_restart_reads_the_accounts_root_from_rendered_settings` | `blocked=[]` | `7-*.txt` |
| 8 | pass | rebase-merge present, 1 `UU`, log `Pull successful`; Stop ok; notice `...; Harness landing waits: a rebase is stopped in the harness home (1 conflicted path(s)); nothing was changed...`; HEAD, rebase-merge, index, stash list, `git diff` sha256: `fingerprints identical`; no overlay | the same fingerprints, no notice from the landing | `8-*.txt` |
| 9 | pass | keystone layout; after: `hooks/post-commit.auto-push-disabled`, `keystone-hooks/preserved/post-commit.auto-push-disabled`, dispatcher kept; `refs/backups on origin after 6 s: 0`; opt-in template `unchanged, executable` | `refs/backups ... after 6 s: 1`, both legacy copies active | `9-*.txt` |
| 10 | pass | 22 lines equal to the expected stand-ins (printed; no stand-in is in 100 or more tracked lines, so the 100-line rule leaves none out), `contains demo-owner: False; shorter than 4: 0; shipped defaults ...: 0`; commit adding `acct-test-123`: `rc=1`, `FAIL: private literal (private-literals.txt line 5)`; unrelated commit `rc=0` | P7's manual init: `literal lines: 0` | `10-*.txt` |
| 11 | pass | (921b5128) second Stop: `unchanged` (overlay, settings, record, list, local config sha256); cost below; stale pre-commit: `land --state` = `hooks`, notice `init step 5 reinstalled the git hooks that differed from hooks/git-hooks/`, log `1 step-5-only run(s)`, `result=hooks-refreshed`, installed = new source, nine lines, hashes unchanged; third Stop: hashes unchanged, 0 log lines added (the same hashes and lines as on 96bcb8f2 and 26a7ea7a) | cost baseline | `review-nv1/11-*.txt` (96bcb8f2: `review-v1/11-*.txt`; 26a7ea7a: `review-r4/11-*.txt`; 98d153ad: `11-*.txt`) |
| 12 | pass | both Stops ok; `overlays: 1`; nine lines; log `landings=1`, `result=landed` x1, `result=skipped` x1 (the other Stop skipped on the lock) | nothing lands | `12-*.txt` |
| 13 | pass | fresh clone (1 reflog entry, state `none`): `stop verdict: ok`, `notices: 0`, overlay, list, record and landing log absent, `local git config: unchanged` | the same | `13-*.txt` |
| 14 | pass | `/home/alice/.claude`, post-pull Stop: nine lines; `private-literals.txt seeded with 21 value(s)` (36 before commit 37, review F3) | nothing lands (`machine-form=no`, `pre-commit: NOT installed`) | `14-*.txt` |
| 15 | pass | `old pid gone`; new daemon `bash <home>/hooks/git-fswatch.sh <home>`, the current file, `FSWATCH_DEBOUNCE=7: 1 GIT_AUTO_PUSH entries: 0`; log `fswatch restarted=1 busy=0 busy-home=0 stopped-integration=0 later=0 failed=0` | `old pid STILL RUNNING` | `15-*.txt` |
| 16 | pass | all 58 Stop replays of the after evidence of acceptance 1-16 and the extra runs: `stop verdict: ok` (0 not ok; the two refused /merge rows of `mergesh-detail` are `NOT ok` on this head, round 2's head and d625284 alike: their home keeps fe7700c8's code, whose coordinator blocks on the auto_commit phase, as in the refused merge rows; before: 18 ok); a directory and a dangling symlink at the overlay path: `Harness landing failed at the overlay step (see logs/landing.log) (done so far: 1 legacy auto-push hook(s) renamed aside); it runs again at the next turn end.`, state stays `upgraded`, `filter: unset`, the second Stop fails again (nothing claims landed); once removed, the next Stop lands; on 26a7ea7a the 11 Stop replays of `review-r4/` (11, `n1`, `pullsh`, `fswatchpop`) are `ok` as well, on 96bcb8f2 the 13 of `review-v1/` (11 and V1-1's two repro scripts, three of their Stops with `index.lock` held), on 921b5128 the 28 of `review-nv1/` (11, NV-1's repro in both cases, the NF-3 and V1-1 repros again; seven of their Stops with `index.lock` held), in review NV1-2's runs the 16 on 10d7d254's kit and the 25 on 760f06e7's (`review-nv12/*-before.txt`, `*-after.txt`: the four `oddpath` cases, `crash`, `oddstrict` and, on 760f06e7, the three `oddalone` cases; per kit four Stops with `index.lock` held and one with `repair_pop` made to raise), and in review NVF's runs the 81 on 760f06e7's kit and the 81 on this head's (`review-nvf/*-before.txt`, `*-after.txt`: 26 scenarios per kit, every hook of every Stop `rc=0 ok`; per kit 18 Stops with `index.lock` held and three with a fault injected in `render-settings`) | the same Stops `ok`, nothing lands (`state: n/a (no landing code)`) | `16-*.txt` |
| 17 | pass | (this head, 1071ad39) `117 passed` (`tests/test_settings_filter.py tests/test_landing.py`, HOME at a scratch home with an empty global git config, CLAUDE_CONFIG_DIR and TMPDIR scratch directories), again with HOME at an empty dir, no global git config file and no CLAUDE_CONFIG_DIR (117 passed; 0 files written under HOME or CLAUDE_CONFIG_DIR in either run), and the first again on the trial merge of this head with PR #6's head 0d266922 (its hermetic `conftest.py`; 117 passed; on 760f06e7's trial merge 114 and 114); every fix of review round 1 has a test case that fails on the code before it (`fix/evidence/c1-before.txt` ... `c13-before.txt`, `c5-timed-out-before.txt`; control cases that pass before as well: the two non-session cases of the push-switch test, the allow case of the cut-short test, and the left-over-lock case once its own fix was in), and so does every fix of review round 2 (`r3/evidence/new-tests-before-after.txt`: 10 failed on 1962cb6's code, 10 passed; `work/evidence/new-tests-before-after.txt`: 9 failed with each commit's own code files from its parent, 9 passed) and both routed fixes (in the latter file), and both fixes of review round 3 (`work/evidence/review-r3/new-tests-before-after.txt`: 4 failed with each commit's own code files from its parent, 4 passed), and the three of round 4 (`review-r4/new-tests-before-after.txt`: 4 failed with each commit's own code file from its parent, all 5+3+2 selected cases passed on 26a7ea7a), and V1-1's (`review-v1/new-test-before-after.txt`: failed with 26a7ea7a's code files and with either of commit 50's two code files alone, passed with both), and NV-1's (`review-nv1/new-tests-before-after.txt`: 3 failed with 96bcb8f2's code files, 4 with commit 51's `land` alone, 1 with its `render-settings` alone; all 6 selected cases passed with both, the NF-3, V1-1 and LH-7 tests among them), and NV1-2-1's and NV1-2-2's (`review-nv12/new-tests-before-after.txt`: the first's 2 cases failed with 10d7d254's `render-settings`, the second with 10d7d254's `land`, alone and with its `render-settings`; all 3 cases passed on 760f06e7), and NVF-1's and NVF-2's (`review-nvf/new-tests-before-after.txt`: with this head's tests, the first's two new cases failed with 760f06e7's `render-settings`, the second with 7a401465's `land`; all 5 selected cases passed on this head) | round 1, 64 tests: this branch's tests against d625284's code `31 failed, 33 passed` | `review-nvf/unit-a.txt`, `review-nvf/unit-b.txt`, `review-nvf/merged-p8-unit-a.txt`, `review-nvf/new-tests-before-after.txt`, `review-nv12/new-tests-before-after.txt`, `review-nv1/new-tests-before-after.txt` (760f06e7: `review-nv12/17-*.txt`; 10d7d254: `review-nv1v/17-*.txt`; 921b5128: `review-nv1/17-*.txt`; 96bcb8f2: `review-v1/17-*.txt`, `review-v1/new-test-before-after.txt`; 26a7ea7a: `review-r4/17-*.txt`), `new-tests-before-after.txt` |
| 18 | pass (at 98d153ad) | CI below, run at 98d153ad and not again for commits 47-56: no new failure; net code below (this head) | CI below | `work/ci/out-head/`, `work/ci/out-base/` |
| 19 | pass | (this head) personal values checked: 25 (seeded from fe7700c8 and 09ab15bc in the sandbox, plus the history's author and committer e-mails and the fe7700c8 fixture identity e-mail); in the diff, the commit messages, this text and the evidence files: 0 lines with a personal value, 0 secret-pattern lines, 0 other e-mail addresses; the CI step logs print the tracked tree's own content, 63 such lines and 1 secret-pattern line on d625284 and the same 63 and 1 on 98d153ad (CI not run again); `git diff d625284 -- commands/commit.md commands/close.md agents/changelog-analyst.md`: 0 lines; model identifiers outside the commit trailers: 0; all 56 commit messages end with the two trailer lines (`work/r4/privacy-run-nvf.txt`; the diff and messages of commits 55 and 56, this text, `PR-DESC.md`, the record and `review-nvf/` scanned alone as well (the session owner's address and login name given as values too, both already among the 25), with the same zeros and both commits' author and committer `noreply@anthropic.com`; matched without regard to case, the 9 record links of `PR-DESC.md` hold the repository owner's login in their URL, and no other line of these files holds a value (`review-nvf/privacy-new.txt`); 760f06e7's run: `privacy-run-nv12.txt`, `review-nv12/privacy-new.txt`; 10d7d254's run: `privacy-run-nv1v.txt`, `review-nv1v/privacy-new.txt`; 921b5128's run: `privacy-run-nv1.txt`, `review-nv1/privacy-new.txt`; 96bcb8f2's run: `privacy-run-v1.txt`; 26a7ea7a's: `privacy-run-r4.txt`) | - | privacy run |

Cost (acceptance 11), interleaved rounds of the median of 10 runs of `bash hooks/auto-commit.sh`
on the landed scenario-3 home against d625284's kit after P7's manual init (no other job of this
session ran; the machine's other load as the load average shows). The landed home on 921b5128
(this head's landed fast path, against a d625284 kit rebuilt for it) and on 96bcb8f2; the two other
rows on 26a7ea7a, whose landed fast path commits 50-56 do not change (their lines run only after a
repair, which none of these homes needs):

| Home | after, median ms per round | before (d625284), median ms per round | difference |
|---|---|---|---|
| landed home (921b5128) | 34.1, 29.6, 31.1, 29.2, 31.6, 36.8 | 11.8, 11.5, 10.4, 12.5, 11.8, 11.0 | +16.7 to +25.8 |
| landed home (96bcb8f2) | 30.7, 34.0, 29.8, 29.9, 32.2, 31.8 | 12.1, 11.4, 10.4, 10.4, 11.9, 11.9 | +18.6 to +22.6 |
| landed home (26a7ea7a) | 28.7, 27.9, 29.4, 28.8, 27.2, 26.6 | 11.6, 10.7, 11.5, 12.3, 10.6, 10.9 | +15.7 to +17.9 |
| landed home, one stash entry kept (26a7ea7a) | 29.7, 28.4, 32.0, 28.0 | 13.9, 11.5, 10.9, 10.1 | +15.8 to +21.1 |
| landed home, a current git-fswatch daemon running on it (26a7ea7a) | 31.9, 37.1, 32.6, 36.4 | 11.4, 10.0, 10.7, 10.2 | +20.5 to +27.1 |

(load average 0.39 0.60 0.73 at the start of 921b5128's rounds, 0.56 0.61 0.76 at 96bcb8f2's, 0.69 0.63 0.66 at 26a7ea7a's; no other job of this session ran; every round in a PID namespace with `env -i`; `work/evidence/review-nv1/11-cost.txt` (921b5128), `work/evidence/review-v1/11-cost.txt` (96bcb8f2), `work/evidence/review-r4/11-cost.txt`, `11-cost-stash.txt`, `11-cost-daemon.txt` (26a7ea7a); 98d153ad's runs in `work/evidence/11-cost*.txt`; the daemon row's homes run a git-fswatch daemon of their own current code, started after the landing, so it is not stale and is not restarted.)

Landing duration (F8 of review round 1): a whole pre-landing Stop that lands the home took
1.60 to 1.78 s in acceptance 1-4 and 14 at 98d153ad (`total=` of the replay, every Stop hook
included); with 3500 empty repositories under `$HOME` the landing alone took 8.22 s
(`review-r2/rq4-after.txt`, `scan=timed-out`; 16.26 s on round 2's head). Measured on round 2's head
(1962cb6), the landing alone took 0.64 s in a test home, about 2 s with one daemon restart
(acceptance 15's log, `acc2/evidence/15-after-timing.txt`), and 9.4 s with three daemons that need
the KILL (`fix/evidence/landing-duration.txt`; 20.0 s before the time budget); round 2's fixes'
changes on those paths are the centisecond start test (the same one `stat` and one `getconf`) and
one `git ls-tree` in the seeding. The
bound by construction: the `$HOME` scan's `find` stops at 5 s; the loop over the repositories it
found takes no new one after 8 s (the harness home's own comes first); a daemon restart starts
only while the landing is under 8 s and takes at most 3 s (TERM wait) + 0.2 s + 1 s (start check),
so the last one ends by about 12.2 s; then the settings step and init steps 3-5 (0.6 s in the test
home): about 13 s, whatever the number of repositories under `$HOME`. A landing that waits (a busy
daemon on the home, a failed step) repeats the scan at the next Stop.

Not run: the systemd branch of the daemon restart (`systemctl [--user] restart` for a daemon whose
cgroup names a `git-fswatch@<instance>.service` unit) is UNVERIFIED: this container runs no systemd
(`/run/systemd/system` is absent, PID 1 is `process_api`) and no test covers it; every daemon restart
above went through the stop-and-start path.

Extra runs (`work/evidence/`): `matrix`, `matrix-mergesh`, `mergesh-detail` and `expired` (above), `common` (the 100-line rule; `r3/evidence/common-prevhead.txt` on round 2's kit), `classes` (the per-class table), `occ-p8` (tracked lines holding a seeded value at this head, PR #6's head and the trial merge), `ds` (the doc-sync exception, before/after), `pullsh` and `fswatchpop` (the two routed defects, before/after), `n1` (review N1: a CLI
`model` write on a landed home, then /pull or fswatch's `safe_pull` after a Stop, and /pull before
any Stop; before/after, and on 1d10ae00's kit in `review-r3/prevhead/`),
`busy` (a stale daemon in its git work, then the landed-home retry of the toy repository's daemon),
`wedge` (a busy daemon at Stop 1, a CLI write, then Stops 2 and 3: lands at Stop 2 with the entry
kept), `window` (the CLI writes between the settings step and the render: Stop 1 lands and names
the dropped entry), `costd` (cost with a current daemon running), `facts`, `facts1`, `fact9`;
review round 2's repro scripts (`review-r2/*-after.txt`, per finding above); V1-1's and NV-1's
repros (`review-v1/`, `review-nv1/`, above); the trial merge with
PR #6's head 0d266922 (at 98d153ad) re-ran acceptance 1, 2, 3, 4, 6, 10 and 15, `ds`, `pullsh`, `fswatchpop` and
`n1` in a kit built from the merged tree: all pass (the nine lines in 1-4, the stand-in list in 10, the restart in 15, and the same `ds`, `pullsh`, `fswatchpop` and `n1` outcomes as on this head) (`work/evidence-merged/`); review NF-1's
experiment and gap scenarios, NF-2's and NF-3's before/after (`review-r4/`, above).
Round 1's mutation checks: 22 of 22 removed fixes are caught by `tests/test_landing.py`
(`work/evidence/mutations.txt`); each fix since then has its own failing-before test instead.

<details><summary>Acceptance 1 output (this branch at 98d153ad)</summary>

```
# 1 (after) kit=kit-n1 source=98d153adb524 2026-10-23T08:04:19Z ns=ns.sh load: 1.24 0.71 0.76
live-home: rev=fe7700c86976 edit=cli-conflict new=de15b576c676 status=1
== fswatch pull (the old safe_pull)
CONFLICT (content): Merge conflict in settings.json
✓ Stashed changes restored
[2026-10-23 08:04:21] [SUCCESS] Stashed changes restored
safe_pull rc=0
== git status --porcelain after the pull
UU settings.json
== pre-landing session's Stop
[stop-old] Stop tool=None agent=None hooks=4 total=1760ms blocked=[] errors=[]
notice (stop-workflow-coordinator.py): Harness landing: P7 landed on this home: settings.json rendered from the overlay, settings filter registered, pre-commit hook installed; overlay migrated from the settings before the pull; 1  [...]
stop verdict: ok
== assert-landed
stop verdict: ok
settings.json: json=yes markers=0 machine-form=yes
index: unmerged=0 settings.json-staged=no other-staged=0
filter: clean=set smudge=set required=true   record: present mode=600
overlay: present mode=600 git-auto-push-1=no live-model=kept live-allow=kept
semantic diff vs the live file: only the intended differences
pre-commit: installed
private-literals: present mode=600 lines>=1 seeded-values-in-output=0
legacy post-commit hooks active: 0
stash entries: 1 (kept)
# exit=0
```
</details>
<details><summary>Acceptance 2 output (this branch at 98d153ad)</summary>

```
# 2 (after) kit=kit-n1 source=98d153adb524 2026-10-23T08:04:24Z ns=ns.sh load: 1.30 0.73 0.77
live-home: rev=fe7700c86976 edit=cli-merge new=de15b576c676 status=1
== /pull (the old hooks/pull.sh)
  • Review changes: git log --oneline -5
  • Check status: git status
pull.sh rc=0
== git status --porcelain after the pull
 M settings.json
== post-pull session's Stop
[stop-new] Stop tool=None agent=None hooks=3 total=1757ms blocked=[] errors=[]
notice (stop-workflow-coordinator.py): Harness landing: P7 landed on this home: settings.json rendered from the overlay, settings filter registered, pre-commit hook installed; overlay migrated from the settings before the pull; pr [...]
stop verdict: ok
== assert-landed
stop verdict: ok
settings.json: json=yes markers=0 machine-form=yes
index: unmerged=0 settings.json-staged=no other-staged=0
filter: clean=set smudge=set required=true   record: present mode=600
overlay: present mode=600 git-auto-push-1=no live-model=kept live-allow=kept
semantic diff vs the live file: only the intended differences
pre-commit: installed
private-literals: present mode=600 lines>=1 seeded-values-in-output=0
legacy post-commit hooks active: 0
stash entries: 0
# exit=0
```
</details>
<details><summary>Acceptance 3 output (this branch at 98d153ad)</summary>

```
# 3 (after) kit=kit-n1 source=98d153adb524 2026-10-23T08:04:28Z ns=ns.sh load: 1.36 0.75 0.77
live-home: rev=fe7700c86976 edit=none new=de15b576c676 status=0
== merge pull
merge rc=0
== pre-landing session's Stop
[stop-old] Stop tool=None agent=None hooks=4 total=1600ms blocked=[] errors=[]
notice (stop-workflow-coordinator.py): Harness landing: P7 landed on this home: settings.json rendered from the overlay, settings filter registered, pre-commit hook installed; overlay migrated from the settings before the pull; pr [...]
stop verdict: ok
== assert-landed (intended differences listed)
stop verdict: ok
settings.json: json=yes markers=0 machine-form=yes
index: unmerged=0 settings.json-staged=no other-staged=0
filter: clean=set smudge=set required=true   record: present mode=600
overlay: present mode=600 git-auto-push-1=no live-model=kept live-allow=kept
semantic diff vs the live file: only the intended differences
pre-commit: installed
private-literals: present mode=600 lines>=1 seeded-values-in-output=0
legacy post-commit hooks active: 0
  intended: env added by the overlay x13; module hook command (PostToolUse) x1; module hook command (PreToolUse) x1; module hook command (UserPromptSubmit) x1; upstream hook command (Stop) added x1; upstream hook command (Stop) re [...]
# exit=0
```
</details>
<details><summary>Acceptance 4 output (this branch at 98d153ad)</summary>

```
# 4 (after) kit=kit-n1 source=98d153adb524 2026-10-23T08:04:32Z ns=ns.sh load: 1.65 0.82 0.80
live-home: rev=09ab15bc7b5e edit=none new=de15b576c676 status=0
old settings GIT_AUTO_PUSH: 1
== fswatch pull
safe_pull rc=0
== pre-landing session's Stop (old settings of 09ab15bc)
[stop-old] Stop tool=None agent=None hooks=4 total=1600ms blocked=[] errors=[]
notice (stop-workflow-coordinator.py): Harness landing: P7 landed on this home: settings.json rendered from the overlay, settings filter registered, pre-commit hook installed; overlay migrated from the settings before the pull (GI [...]
stop verdict: ok
== assert-landed (intended differences listed)
stop verdict: ok
settings.json: json=yes markers=0 machine-form=yes
index: unmerged=0 settings.json-staged=no other-staged=0
filter: clean=set smudge=set required=true   record: present mode=600
overlay: present mode=600 git-auto-push-1=no live-model=kept live-allow=kept
semantic diff vs the live file: only the intended differences
pre-commit: installed
private-literals: present mode=600 lines>=1 seeded-values-in-output=0
legacy post-commit hooks active: 0
  intended: env added by the overlay x13; module hook command (PostToolUse) x1; module hook command (PreToolUse) x1; module hook command (UserPromptSubmit) x1; upstream env.GIT_AUTO_PUSH (D1: 1 -> 0) x1; upstream hook command (Sto [...]
== landing output naming GIT_AUTO_PUSH
GIT_AUTO_PUSH not migrated: automatic push is opt-in
not migrated: GIT_AUTO_PUSH (automatic push is opt-in; set it in settings.machine.json)
== render-settings migrate --from 09ab15bc in a scratch clone of this code
render-settings: wrote settings.machine.json (mode 0600) from 09ab15bc:settings.json
  not migrated: GIT_AUTO_PUSH (automatic push is opt-in; set it in settings.machine.json)
migrate rc=0
overlay env GIT_AUTO_PUSH: absent
# exit=0
```
</details>
<details><summary>Acceptance 5 output (this branch at 98d153ad)</summary>

```
# 5 (after) kit=kit-n1 source=98d153adb524 2026-10-23T08:04:37Z ns=ns.sh load: 1.76 0.86 0.81
live-home: rev=fe7700c86976 edit=none new=de15b576c676 status=0
merge rc=0
notice (stop-workflow-coordinator.py): Harness landing: P7 landed on this home: settings.json rendered from the overlay, settings filter registered, pre-commit hook installed; overlay migrated from the settings before the pull; pr [...]
stop verdict: ok
== overlay env GIT_AUTO_PUSH=1, render, check
render: render-settings: settings.json rendered (overlay: present; modules: paseo)
check rc=0
4:[info] env.GIT_AUTO_PUSH is "1" in settings.machine.json: automatic pushes are on
== the key removed, render, check
render: render-settings: settings.json rendered (overlay: present; modules: paseo)
check rc=0
(no line naming GIT_AUTO_PUSH)
# exit=0
```
</details>
<details><summary>Acceptance 6 output (this branch at 98d153ad)</summary>

```
# 6 (after) kit=kit-n1 source=98d153adb524 2026-10-23T08:04:41Z ns=ns.sh load: 1.78 0.88 0.81
live-home: rev=09ab15bc7b5e edit=none new=de15b576c676 status=0
safe_pull rc=0
stop verdict: ok
rendered settings GIT_AUTO_PUSH: 0
== a plain change in the toy repository; the pre-landing session's Stop (env GIT_AUTO_PUSH=1, no CLAUDE_HOME)
stop verdict: ok
checkpoint refs on origin after 6 s: 0
== positive control: overlay env GIT_AUTO_PUSH=1, rendered, the same Stop
render: render-settings: settings.json rendered (overlay: present; modules: paseo)
stop verdict: ok
checkpoint refs on origin after 1 s: 1
== non-Claude control: a plain shell, GIT_AUTO_PUSH=1, write_checkpoint in a scratch repository
write_checkpoint rc=0
non-Claude control: checkpoint refs on origin: 1
# exit=0
```
</details>
<details><summary>Acceptance 7 output (this branch at 98d153ad)</summary>

```
# 7 (after) kit=kit-n1 source=98d153adb524 2026-10-23T08:04:55Z ns=ns.sh load: 1.73 0.90 0.82
live-home: rev=fe7700c86976 edit=none new=de15b576c676 status=0
merge rc=0
notice (stop-workflow-coordinator.py): Harness landing: P7 landed on this home: settings.json rendered from the overlay, settings filter registered, pre-commit hook installed; overlay migrated from the settings before the pull; pr [...]
stop verdict: ok
== overlay CLAUDE_HARD_BANNED_SCRIPTS=demo-recovery, rendered
render: render-settings: settings.json rendered (overlay: present; modules: paseo)
== PreToolUse Bash 'bash demo-recovery.sh' with the old settings (no CLAUDE_HOME)
[pre-old] PreToolUse tool=Bash agent=None hooks=20 total=1714ms blocked=[('pretool-bash-safety.sh', 'BLOCK(exit2)')] errors=[]
    -> pretool-bash-safety.sh BLOCK(exit2): BLOCKED: hard-banned script 'demo-recovery' is PERMANENTLY FORBIDDEN | Command: bash demo-recovery.sh | REASON: It manages session state or restarts daemons and can kill all sessions. On [...]
# exit=0
```
</details>
<details><summary>Acceptance 8 output (this branch at 98d153ad)</summary>

```
# 8 (after) kit=kit-n1 source=98d153adb524 2026-10-23T08:05:01Z ns=ns.sh load: 1.92 0.97 0.85
live-home: rev=fe7700c86976 edit=none new=de15b576c676 status=0
== fswatch pull
CONFLICT (content): Merge conflict in settings.json
✓ Pull successful
[2026-10-23 08:05:03] [SUCCESS] Pull successful
safe_pull rc=0
rebase-merge: present  status: 1 UU path(s)
before: HEAD=de15b576c676 rebase-merge=ce07afe758c61e18 index=89658272d07bd950 stash=e3b0c44298fc1c14 diff=8121e8b00c8613c8
== pre-landing session's Stop
[stop-old] Stop tool=None agent=None hooks=4 total=1153ms blocked=[] errors=[]
notice (stop-workflow-coordinator.py): Checkpoint snapshot refused by the settings check (render-settings check --staged): nothing written, see logs/checkpoint.log; Harness landing waits: a rebase is stopped in the harness home (1 [...]
stop verdict: ok
after:  HEAD=de15b576c676 rebase-merge=ce07afe758c61e18 index=89658272d07bd950 stash=e3b0c44298fc1c14 diff=8121e8b00c8613c8
fingerprints identical
overlay: ls: cannot access '/root/.claude/settings.machine.json': No such file or directory
# exit=0
```
</details>
<details><summary>Acceptance 9 output (this branch at 98d153ad)</summary>

```
# 9 (after) kit=kit-n1 source=98d153adb524 2026-10-23T08:05:05Z ns=ns.sh load: 1.92 0.97 0.85
live-home: rev=fe7700c86976 edit=none new=de15b576c676 status=0
== keystone layout before the pull
KEYSTONE_DIR=<home>/.git/keystone-hooks
PRIOR_HOOKSPATH=<unset/default>
REHOMED_HOOKS=post-commit
hooks/post-commit: legacy=1 exec=y
keystone-hooks/preserved/post-commit: legacy=1 exec=y
keystone-hooks/post-commit: legacy=0 exec=y
== the current opt-in template installed on purpose in a scratch repository under HOME
merge rc=0
notice (stop-workflow-coordinator.py): Harness landing: P7 landed on this home: settings.json rendered from the overlay, settings filter registered, pre-commit hook installed; overlay migrated from the settings before the pull; pr [...]
stop verdict: ok
legacy post-commit hooks active: 0
== post-commit files after the Stop
keystone-hooks/post-commit: legacy=0 exec=y
hooks/post-commit.auto-push-disabled: legacy=1 exec=y
keystone-hooks/preserved/post-commit.auto-push-disabled: legacy=1 exec=y
== a commit in the home from a plain shell, GIT_AUTO_PUSH unset
commit rc=0
refs/backups on origin after 6 s: 0
opt-in template in the scratch repository under HOME: unchanged, executable
# exit=0
```
</details>
<details><summary>Acceptance 10 output (this branch at 98d153ad)</summary>

```
# 10 (after) kit=kit-n1 source=98d153adb524 2026-10-23T08:05:15Z ns=ns.sh load: 2.08 1.03 0.87
live-home: rev=fe7700c86976 edit=none new=de15b576c676 status=0
synthetic revision: 12 code defaults found, all stand-ins: True
home moved to NEW with a checkout; reflog holds the synthetic commit: 1
== pre-landing session's Stop
notice (stop-workflow-coordinator.py): Harness landing: P7 landed on this home: settings.json rendered from the overlay, settings filter registered, pre-commit hook installed; overlay migrated from the settings before the pull; pr [...]
stop verdict: ok
private-literals.txt: mode=600 lines=22
equals the expected stand-ins (in file order):
  demo-web-dev
  demo-api-dev
  /opt/demo/bin/allow-restart
  demo-daemon
  acct-test-123
  acct-test-456
  /opt/demo/accounts
  -opt-demo-dot-claude
  demo-recovery
  demo-family
  demo-bot@example.invalid
  acct-test-789
  /opt/demo/bin/graphify
  /opt/demo/bin/tool
  /opt/demo/notes
  demo@example.invalid
  git@example.invalid:demo-owner
  /home/demo-user
  /opt/demo/private-proj
  demo-private-proj
  /opt/demo/private-tree
  /opt/demo/ws-marker
contains demo-owner: False; shorter than 4: 0; shipped defaults (session-recovery, /var/tmp/claude-scratch): 0
land: seeded overlay-env=13 permission-paths=2 git-e-mail=1 check-markers=6
== a commit adding a file that contains acct-test-123
commit rc=1
FAIL: private literal (private-literals.txt line 5) -> sandbox-private.txt:1
== an unrelated public change
commit rc=0
# exit=0
```
</details>
<details><summary>Acceptance 11 output (921b5128)</summary>

```
# 11 (after) kit=kit-after source=921b5128e6f8 2026-10-23T19:45:30Z ns=ns.sh (own PID namespace) load: 0.35 0.61 0.74
live-home: rev=fe7700c86976 edit=none new=c43489e7f9b4 status=0
merge rc=0
notice (stop-workflow-coordinator.py): Harness landing: P7 landed on this home: settings.json rendered from the overlay, settings filter registered, pre-commit hook installed; overlay migrated from the settings before the pull; pr [...]
stop verdict: ok
== idempotent: a second Stop on the landed home
stop verdict: ok
overlay=481dff8459aa6eab settings=5f78e77409b4d900 record=a45a5b8c06a9e548 list=6cc128281cb9bdc4 config=91e98a4155254f17
second Stop: unchanged
== cost: median of 10 timed runs of hooks/auto-commit.sh (stop.json on stdin, cwd the harness home)
status lines: 0
auto_commit phase ms: median=33.0 min=28.5 max=34.8 (n=10)
last stdout line: ✅ No changes to checkpoint.
== stale installed hook: a stand-in comment line committed to hooks/git-hooks/pre-commit
commit rc=0
land --state before the Stop: hooks
notice (stop-workflow-coordinator.py): Harness landing: init step 5 reinstalled the git hooks that differed from hooks/git-hooks/.
stop verdict: ok
installed pre-commit: identical to the new source
stop verdict: ok
settings.json: json=yes markers=0 machine-form=yes
index: unmerged=0 settings.json-staged=no other-staged=0
filter: clean=set smudge=set required=true   record: present mode=600
overlay: present mode=600 git-auto-push-1=no live-model=kept live-allow=kept
semantic diff vs the live file: only the intended differences
pre-commit: installed
private-literals: present mode=600 lines>=1 seeded-values-in-output=0
legacy post-commit hooks active: 0
hashes after the step-5 run: unchanged
log: 1 step-5-only run(s); last result: result=hooks-refreshed
stop verdict: ok
third Stop: hashes unchanged, log lines added: 0
# exit=0
```
</details>
<details><summary>Acceptance 12 output (this branch at 98d153ad)</summary>

```
# 12 (after) kit=kit-n1 source=98d153adb524 2026-10-23T08:05:19Z ns=ns.sh load: 2.23 1.08 0.89
live-home: rev=fe7700c86976 edit=none new=de15b576c676 status=0
merge rc=0
== two pre-landing sessions' Stops started together
[stop-a] Stop tool=None agent=None hooks=4 total=1670ms blocked=[] errors=[]
stop verdict (a): ok
notice (a): Harness landing: P7 landed on this home: settings.json rendered from the overlay, settings filter registered, pre-commit hook installed; overlay migrated from t
[stop-b] Stop tool=None agent=None hooks=4 total=831ms blocked=[] errors=[]
stop verdict (b): ok
notice (b): Harness landing: another session is landing this home right now; nothing done here.
overlays: 1
settings.json: json=yes markers=0 machine-form=yes
index: unmerged=0 settings.json-staged=no other-staged=0
filter: clean=set smudge=set required=true   record: present mode=600
overlay: present mode=600 git-auto-push-1=no live-model=kept live-allow=kept
semantic diff vs the live file: only the intended differences
pre-commit: installed
private-literals: present mode=600 lines>=1 seeded-values-in-output=0
legacy post-commit hooks active: 0
log: landings=1 results:       1 result=landed       1 result=skipped 
# exit=0
```
</details>
<details><summary>Acceptance 13 output (this branch at 98d153ad)</summary>

```
# 13 (after) kit=kit-n1 source=98d153adb524 2026-10-23T08:05:23Z ns=ns-alt.sh load: 2.30 1.12 0.90
== fresh clone: reflog entries 1; state none
[fresh] Stop tool=None agent=None hooks=3 total=828ms blocked=[] errors=[]
stop verdict: ok
notices: 0
overlay: absent  list: absent  record: absent  landing log: absent
local git config: unchanged
# exit=0
```
</details>
<details><summary>Acceptance 14 output (this branch at 98d153ad)</summary>

```
# 14 (after) kit=kit-n1 source=98d153adb524 2026-10-23T08:05:25Z ns=ns-alt.sh load: 2.30 1.12 0.90
live-home: rev=fe7700c86976 edit=none new=de15b576c676 status=0
== merge pull (harness at /home/alice/.claude)
merge rc=0
== post-pull session's Stop
[stop-new] Stop tool=None agent=None hooks=3 total=1784ms blocked=[] errors=[]
notice (stop-workflow-coordinator.py): Harness landing: P7 landed on this home: settings.json rendered from the overlay, settings filter registered, pre-commit hook installed; overlay migrated from the settings before the pull; pr [...]
stop verdict: ok
stop verdict: ok
settings.json: json=yes markers=0 machine-form=yes
index: unmerged=0 settings.json-staged=no other-staged=0
filter: clean=set smudge=set required=true   record: present mode=600
overlay: present mode=600 git-auto-push-1=no live-model=kept live-allow=kept
semantic diff vs the live file: only the intended differences
pre-commit: installed
private-literals: present mode=600 lines>=1 seeded-values-in-output=0
legacy post-commit hooks active: 0
# exit=0
```
</details>
<details><summary>Acceptance 15 output (this branch at 98d153ad)</summary>

```
# 15 (after) kit=kit-n1 source=98d153adb524 2026-10-23T08:05:29Z ns=ns.sh load: 2.35 1.15 0.91
live-home: rev=fe7700c86976 edit=none new=de15b576c676 status=0
old daemon: pid running=yes environ FSWATCH_DEBOUNCE=7: 1 GIT_AUTO_PUSH: 0
== merge pull
merge rc=0
== pre-landing session's Stop with --env GIT_AUTO_PUSH=1
notice (stop-workflow-coordinator.py): Harness landing: P7 landed on this home: settings.json rendered from the overlay, settings filter registered, pre-commit hook installed; overlay migrated from the settings before the pull; pr [...]
stop verdict: ok
old pid gone
new daemon: cmdline=bash <home>/hooks/git-fswatch.sh <home>  cwd=<home>
new daemon script is the current file: yes
new daemon environ: FSWATCH_DEBOUNCE=7: 1 GIT_AUTO_PUSH entries: 0
fswatch restarted=1 busy=0 busy-home=0 stopped-integration=0 later=0 failed=0
# exit=0
```
</details>
<details><summary>Acceptance 16 output (this branch at 98d153ad)</summary>

```
# 16 (after) kit=kit-n1 source=98d153adb524 2026-10-23T08:05:39Z ns=ns.sh load: 2.68 1.26 0.95
== forced failure: a directory at the overlay path
merge rc=0
notice (stop-workflow-coordinator.py): Harness landing failed at the overlay step (see logs/landing.log) (done so far: 1 legacy auto-push hook(s) renamed aside); it runs again at the next turn end.
stop verdict: ok
state after: upgraded  filter: unset
second Stop, failure notices: 1
== the directory removed: the next Stop
notice (stop-workflow-coordinator.py): Harness landing: P7 landed on this home: settings.json rendered from the overlay, settings filter registered, pre-commit hook installed; overlay migrated from th
stop verdict: ok
state after: landed
== forced failure: a dangling-symlink at the overlay path
merge rc=0
notice (stop-workflow-coordinator.py): Harness landing failed at the overlay step (see logs/landing.log) (done so far: 1 legacy auto-push hook(s) renamed aside); it runs again at the next turn end.
stop verdict: ok
state after: upgraded  filter: unset
second Stop, failure notices: 1
== the dangling-symlink removed: the next Stop
notice (stop-workflow-coordinator.py): Harness landing: P7 landed on this home: settings.json rendered from the overlay, settings filter registered, pre-commit hook installed; overlay migrated from th
stop verdict: ok
state after: landed
# exit=0
```
</details>

CI baseline (`.github/workflows/baseline.yml` steps that need no network, python 3.12, scratch HOME,
CLAUDE_CONFIG_DIR, global git config and TMPDIR; the dependency install and the clean-install smoke
were not run: they need the network). Both sides ran on clean clones, d625284 and 98d153ad (not again for commits 47-54):

| Step | d625284 | this branch |
|---|---|---|
| check-staged | rc=0 | rc=0 |
| tests | rc=1 | rc=1 |
| secret-scan | rc=1 | rc=1 |
| bash-n | rc=0 | rc=0 |
| py-compile | rc=0 | rc=0 |
| cleanup-grep | rc=0 | rc=0 |
| public-core | rc=1 | rc=1 |
| verify-claims | rc=0 | rc=0 |
| blackbox | rc=0 | rc=0 |
| evidence-coverage | rc=0 | rc=0 |

pytest (`hooks/tests tests`, `--ignore=tests/generated`): d625284 `319 failed, 6968 passed, 764 skipped, 8 xpassed, 19 warnings, 19 errors in 3707.63s (1:01:47)`; this branch (98d153ad) `319 failed, 7044 passed, 764 skipped, 8 xpassed, 19 warnings, 19 errors in 3947.72s (1:05:47)`.
Failing or erroring test ids: d625284 338, this branch 338; only on this branch: 0; only on d625284: 0.
Every other step's output is the same on both sides once the checkout path is set aside, except `verify-claims`, whose README line numbers moved by the 21 added lines (423, 821, 829 to 444, 842, 850), and blackbox's run time (41 passed on both); `public-core` reports the same 48 author-path residue failures on both sides (a run after review round 2's fixes, at bddf8df5, had 49: commit 44). The pytest step passes 76 more cases on this branch at 98d153ad: the cases of `tests/test_landing.py` then (84 now).
`tests rc=1`, `secret-scan rc=1` and `public-core rc=1` are master's pre-existing failures (phase P8 makes CI green). The dependency install and the clean-install smoke: not run (network), UNVERIFIED.

### Rules added / retired

- Added: none. The landing is a producer step. The `GIT_AUTO_PUSH` "1" line sits inside the existing
  settings check (a changed rule, not a new one).
- Changed, counted as neither: migrate no longer seeds `GIT_AUTO_PUSH` "1" (D1); migrate no longer
  carries hooks upstream unregistered; the checkpoint push and the overlay keys read from the
  rendered settings in pre-landing sessions (D1, D15).
- Retired: none in code. Replaced by the landing: PLAN-v2.md section 4's P0 and P7 human rows, PR #4's
  REQUEST, the earlier P8 prompt's REQUEST steps 1 and 4.
- State, not a rule: beyond the lock and the append-only log, the landing keeps one file,
  `<git common dir>/claude-settings.checked` (empty; review N1, kept by review NF-1's experiment).
  It departs from P7b.md's "add no flag, marker or counter file" and principle 2; recorded under
  "Decisions applied" with the experiment.

### Net code lines

`git diff --numstat origin/master -- hooks scripts schemas` (origin/master = d625284; tests excluded):

- hooks/, schemas/ and scripts/ outside bootstrap and install: +72 -13 = **+59** (cap +60): the trigger
  and notice (`auto-commit.sh` +6), the push switch (`checkpoint-core.sh` +5), the helper
  (`claude_home.py` +19), its call sites (`pretool-bash-safety.sh` +7, `subagent_restart.py` +6), and
  the three pull-path fixes (`pull.sh` +8: the `refs/stash` comparison, its message
  branch and a two-line comment; `git-fswatch.sh` +8: the pop's own status +1, and the same
  `refs/stash` comparison for its push +7, review NF-2).
- scripts/bootstrap and scripts/install/: +627 -6 = **+621** (target +250, over by 371; +469
  after round 1, +549 at round 2's review, +567 after commits 30-36, +33 in commits 37-41: the
  previous home's paths in the seeding +8, the landed repair's dropped entries +10, the landed
  repair gate +8, the loop's time bound +2, the centisecond start test +5; +12 in commits 45-46: the
  landed-home `settings.json` stat, review N1; +7 in commits 47 and 49: the different-mtime test +2,
  the unmerged `settings.json` named apart +5; +3 in commit 50: the landed repair's notice parts
  while `settings.json` stays unmerged +1, its `repair-refused` log result +2, review V1-1; -2 in
  commit 51: `repair_pop` returns the paths git refused, in place of the two `git ls-files -u` reads
  of commits 49 and 50, review NV-1; 0 in commit 52: `cmd_land`'s docstring reworded on its own three
  lines, review NV1-V1; 0 in commit 53: a refused path's control characters replaced in place, the
  docstring reworded on its own two lines, review NV1-2-1; +1 in commit 54: a failed landed repair
  named and logged `repair-failed`, review NV1-2-2; 0 in commit 55: the replaced class widened in
  place, the docstring reworded on its own line, review NVF-1; 0 in commit 56: a failed repair told
  by the exit status and stdout, in place, review NVF-2). The line count understates the size of `land`:
  51 of its 249 lines (20%) are longer than 100 columns (two of them, at 101, from commits 46 and 47,
  and two, at 124 and 129, from commit 54 as commit 56 rewrote them; none from commits 50, 51, 53
  and 55), the longest 237, and
  wrapped at 100
  columns it would be about 300 lines; the other files of the diff are far less dense (lines over 100 characters,
  counted in characters, not bytes, review N2: `render-settings` 5 of 1555, 0.3%, the fifth, at
  113, commit 55's class; `bootstrap` 30 of
  530, 5.7%; `hooks/lib/checkpoint-core.sh` 41 of 819, 5.0%; `hooks/git-fswatch.sh` 3 of 577, 0.5%;
  `hooks/pull.sh` 1 of 215, 0.5%; round 2's text gave bootstrap, git-fswatch.sh and pull.sh in bytes:
  6.8%, 3.3%, 1.4%):
  - `bootstrap` +21: `--steps`, init's own steps without a terminal (R4).
  - `land` 249: header (17), setup (4), own_hooks (5), the landed test and states (22), log and finish (6), legacy hooks with the `$HOME` scan, its 5 s limit, the loop's 8 s cut, the tracked-hook check and the LFS post-commit (R6) (32), the daemon candidates with the centisecond start test (R8) (27), the daemon restart with its busy, stopped, gone, time-budget, systemd and session-environment paths (R8) (57), state and the landed fast path with the repair gate (15), the landed home's `settings.json` stat (review N1, NF-1) (13), the fast path's exit with the daemon check (2), lock, re-check and the landed-home daemon retry (R1, R8) (10), S4 (R2) (10), the landed repair with its `repair-refused` and `repair-failed` results (reviews V1-1, NV-1, NV1-2-2, NVF-2) and the upgraded flow (R1, R2, R9) (16), init steps (R4, R9) (8), blank lines (5).
  - `render-settings` +351: migrate's D1 exclusion, the check line and the hooks rule (+25); the
    land section: helpers and constants (13), rev detection with the clone rule (20), stash match (14), previous settings (14), pop repair, doc-sync and unstaging (36), seeding parsers (20), seeding (61), the notice parts (9), settings.json from HEAD (review round 1's F3, LH-3) (20), the landing flow (49), its log and CLI (19); blank lines (33); docstring, imports and `main` (+18).
  Extensions beyond the R rows, with their cost: `_tracked_hook` and its use in `cmd_migrate` (+16:
  keeps a Stop unblocked once P10 deletes the retired gate's stub); the repair of `settings.json` on a
  landed home (the same `repair_pop` code as S3 and the doc-sync repair, plus +10 to name what it
  drops, review LH-7); the landed-home `settings.json` stat (+14: a P7 defect of the pull paths that
  the landing brings every upgraded home into, review N1, and its older-mtime gap, review NF-1); the cherry-pick, revert and squash-merge S4 entries (+1 line); the landed-home
  restart of a daemon that a later pull made stale (0 lines: the same retry R8 needs); the 100-line
  seeding rule (+10: a filter R5 does not list, decided by review LH-2's experiment); leaving a
  tracked legacy hook alone (+4: R6 renames every copy, but a tracked one is its repository's
  content); the previous home's paths (+8: R5 says "outside the harness home", and these are the
  tracked tree's own script paths, review F3). The comment-only seeding rule of round 1 is gone (-3).
  The rest is required by an R row or by a review finding (round 1: the 15 s bound, the retry, the
  zombie guard, the LFS route, the state-tied checkout; rounds 2-4 and the verifications of 26a7ea7a, 96bcb8f2, 10d7d254 and 760f06e7:
  the rows above and the per-finding tables). The target is not met. Whether a smaller design would pass the acceptance tests is
  untested: no smaller design was built or run, so this text does not claim that one would fail.

### Rollback

Revert the merge commit of this PR (or its 56 commits). Code-wise nothing else changes. On
a home that already landed, what the landing wrote is the state P7's manual steps produce (overlay,
filter, record, pre-commit hook, private-literal list), which stays valid under P7's code; renamed
hooks come back with `mv <name>.auto-push-disabled <name>` (an LFS post-commit the landing put in a
renamed hook's place is git-lfs's own and can stay or go); `logs/landing.log`,
`<git common dir>/claude-landing.lock` and `<git common dir>/claude-settings.checked` can be deleted. Reverting commits 42, 43 and 48 alone brings back /pull's
and fswatch's pop of an older entry and fswatch's "Stashed changes restored" after a failed pop; reverting commits
45-47 alone brings back review N1's refusal of every pull after a CLI write.

### Out of scope, found

Each with the phase that owns it, where one does.

- Fact 1: `hooks/git-fswatch.sh` `safe_pull` pipes its fetch, stash push and pull into `tee` without
  pipefail, so their failures are logged as success (since commit 43 the pop's own status decides,
  the part the review of PR #6 routed here, and since commit 48 `refs/stash` before and after the
  push decides whether anything was stashed, review NF-2; a push that fails is still logged as
  success); landscape F3.b; no phase in PLAN-v2 owns the rest: for the reviewer.
- Fact 9: a home that pulled P7 alone into S3 or S4 never receives P7b by any pull path
  (`fact9-*.txt`); for the reviewer to take up with the owner.
- Round 2's text said "P8 removes most of the occurrences" of the seeded values; that was false
  (review LH-2). With round 2's seeding, the 22 values occur in 750 tracked lines of 76 files at this
  head and, on PR #6's head 0d266922 alone and after a trial merge with it, still in 532 lines of 23
  files, all from one value, 503 of them under `hooks/` (`work/evidence/occ-p8-after.txt`; the same
  counts as at PR #6's earlier head 5e4b97e8): P8 removes 218 of the 750 lines and 63 of that
  value's 595. Owner impact, for the reviewer and P8: with a value seeded that the tree holds in
  hundreds of lines, every checkpoint snapshot of the whole tree is refused at every Stop once one
  more line holding it is in the working tree (`r3/evidence/common-prevhead.txt`:
  `refs/checkpoints/master moved: no`), and a commit that stages such a line is refused. This head
  leaves such a value out (the 100-line rule): its 21 values occur in 213 lines of 54 files at this
  head and in 0 lines on PR #6's head and on the merged tree; a commit or snapshot that adds a line
  holding one of them is refused, as P7 designed a filled list to behave (P8 removes them). Whether
  that one value is personal at all is P8's call: its scrub keeps it in the tree (P8).
- PR #6's identity e-mail (fe7700c8 `hooks/tests/test_git_residual_override.py:134`) is covered by no
  R5 source unless it is the home's git `user.email`; it is not among the history's author or
  committer e-mails. PR #6's other per-class items drawn from landscape C3.c-C3.f (15 values) could not
  be checked by value from here (the landscape redacts them): UNVERIFIED (P8).
- Overlay keys a pre-landing session still lacks until it restarts: `scripts/prune-orphaned-workflow-
  bookmarks.sh` (`WORKFLOW_PRUNE_*`), `scripts/paseo-daemon-ledger.py`, `scripts/paseo-daemon-timers.py`
  and the checkpoint trailer (`hooks/lib/checkpoint-core.sh` `_checkpoint_commit_body`): not one-line
  changes. `hooks/prompt-workflow.py`'s `GRAPHIFY_BIN` reader is P1's file (P1).
- The opt-in template `hooks/git-hooks/post-commit-auto-push:16` reads the committing process's env;
  its copies live in other repositories (R7 names it here; no phase).
- migrate also carries permission entries and env keys upstream removed (they cannot be told from
  personal ones); none of them can block a Stop (P7's migration; for the reviewer).
- `scripts/install/INDEX.md` and `tests/INDEX.md` (doc-sync output) do not list the two new files
  (doc-sync; P10's clean tree).
- Review N1's remaining window: the landed-home fix runs at a Stop, so a /pull run after a CLI
  write of a key the clean form leaves out (`/model`, say, which starts no turn) and before the next
  Stop still meets git's refusal once (`pull.sh rc=1`, `cannot pull with rebase: You have unstaged
  changes`, HEAD unmoved; `n1-after.txt`, `pull-before-any-stop`), and fswatch's `safe_pull` returns 0
  without pulling until then; the Stop of that turn re-records the stat and the next /pull pulls. The
  cause is P7's filter: git trusts a size change of `settings.json` without the filter, and only
  render re-records the stat; `hooks/pull.sh` (`HAS_CHANGES`) or fswatch's `has_changes` could do the
  same before their pull, files P7b.md's DO NOT names (P7's filter and the pull paths; for the
  reviewer). Unchanged as well: a CLI-owned key lives only in the working file, so a stash push that
  includes `settings.json` (it has another change, or the stat is still dirty) holds the file without
  the CLI's value, and a checkout that rewrites the file writes the smudged clean form, with the
  overlay's value if it holds the key (P7's filter; review round 3's
  `verify-f1/evidence/new-landed-model.txt`). The re-record has the window render-settings'
  `refresh_index` has: a `git add settings.json` that lands between its read of the index entry and
  its `--cacheinfo` write (a few milliseconds) is undone in the index, the working file keeping the
  change (P7's `refresh_index` and this fix alike; for the reviewer). The first Stop after each
  write of `settings.json` diffs it through the filter once (review NF-1's experiment, the landing
  alone against 1d10ae00): +84 to +99 ms with a real change, +173 to +202 ms after a CLI-owned key
  (two filter runs; that Stop's auto_commit phase is still below d625284's, which then runs the
  checkpoint path at every Stop); every variant that tells the two apart pays it (P7b).
- With an uncommitted real change in `settings.json` (each Stop then runs the checkpoint path) this
  branch's auto_commit phase is above d625284's by more than the landing: before N1's code
  (1d10ae00) +25.3 to +82.5 ms per later Stop, of which the landing alone is 10.7 to 13.8 ms; this
  head's `land` (kit of 98d153ad with commit 47's `land`) +28.6 to +65.5 ms in the same rounds (`review-r4/nf1-cost-summary-pre.txt`,
  `nf1-land-only-summary.txt`). The rest was not isolated (UNVERIFIED: the two homes differ in what
  the snapshot checks, e.g. the seeded private-literal list, empty after P7's manual init);
  acceptance 11 measures the clean home only (P7b; for the reviewer).
- Review N3: one failure of the 100 tests in 11 full runs on round 2's head and its trial merge
  (the reviewer's sandbox probes ran in the same kit at the time; the id was not captured). Not
  reproduced here: 4 more full runs of the 103 tests with `-rf` at 98d153ad (3 of them while acceptance runs or the CI suite used the machine), all passed; so did acceptance 17's four runs and the CI suite's run of them (`work/evidence/review-r3/n3-runs.txt`, each with `-rf`). Left as
  PLAUSIBLE; a recurrence names its test id (P7b's tests).
- A landed home whose later stash pop left `settings.json` unmerged: settings.json is taken from
  HEAD, and the notice names the live entries upstream's side lacks (commit 38); their values stay in
  the kept stash entry and nothing puts them back. An `INDEX.md` or `CLAUDE.md` unmerged with the
  owner's own change stays unmerged until he resolves it; meanwhile each Stop runs one `git diff` per
  such path and nothing else (commit 39; `review-r2/lh5-after.txt`: 26 to 30 ms per landing run,
  no log line). While a git lock (`index.lock`) refuses the repair of `settings.json` or of a
  doc-sync `INDEX.md` or `CLAUDE.md`, the file keeps its conflict markers until a Stop runs without
  the lock, so a session that starts in between reads an invalid `settings.json` (or a `CLAUDE.md`
  with conflict markers); each such Stop's
  notice names every path refused and its log result is `repair-refused` (commits 50 and 51,
  reviews V1-1 and NV-1: `review-v1/v1-1-detail-after.txt`, `review-nv1/nv1-lock-*-after.txt`), but
  nothing in the landing can write the file while git holds its lock (for the reviewer).
- Review NV1-2-1's fix, widened by NVF-1's, replaces control and line-break characters only
  (`\x00`-`\x1f`, `\x7f`-`\x9f`, U+2028, U+2029). A refused path whose name holds a byte
  that is not UTF-8 reaches `print()` as a lone surrogate: under the C.UTF-8 locale (the kit's, and
  the only UTF-8 locale installed here) python writes it back as the raw byte and the coordinator
  relays it as U+FFFD (`review-nv12/oddpath-nonutf8-*.txt`); with a strict stdout error handler,
  the one python uses under a UTF-8 locale other than C.UTF-8 (en_US.UTF-8, say; emulated with
  `PYTHONIOENCODING=utf-8:strict`), `print()` raises, the log gets `render-settings: land:
  UnicodeEncodeError` and `render-settings` exits 1 with nothing on stdout: on 10d7d254 and 760f06e7
  that Stop gave no landing notice and logged `result=repair-refused` (`review-nv12/oddstrict-*.txt`);
  since commit 56 (review NVF-2) it says "the settings repair failed (see logs/landing.log); it runs
  again at the next turn end" and logs `result=repair-failed` after that line
  (`review-nvf/oddstrict-*.txt`), although git refused the repair and the run failed only at its
  output; the next Stop without the lock repairs the paths (for the reviewer).
- The landed gate (`land:181-189`) reads `git ls-files -u` without `-z`, so a name git quotes there
  (a control character, or a non-ASCII byte with `core.quotePath` at its default:
  `"tools/odd\303\251dir/INDEX.md"`) does not match `INDEX.md|*/INDEX.md`: a doc-sync `INDEX.md` or
  `CLAUDE.md` under such a directory that a later pull left unmerged alone (`settings.json` not
  unmerged) is never repaired on a landed home and stays unmerged, silently, like an owner's own
  conflict (`review-nv12/oddalone-*-after.txt`: a tab and `é` unmerged after two Stops, no log line,
  no notice; a space repaired at the first Stop). With `settings.json` unmerged as well the repair
  runs and takes it (the `oddpath` cases). Pre-existing: the gate's match before commit 39 missed
  such names as well (for the reviewer).
- Integrations that leave no marker file (`git stash apply` by hand, `git checkout -m`, `git
  cherry-pick -n`) look like a pull's stash pop to a landed home's repair when they leave
  settings.json or a doc-sync file unmerged and a stash entry exists (for the reviewer).
- The `$HOME` scan for other repositories stops after 5 s, and the loop over what it found after 8 s
  (commit 40); the repositories not reached keep their legacy hooks. The log (`scan=timed-out`) and
  that Stop's notice say so; nothing records which ones were missed, so a landed home does not scan
  again (for the reviewer).
- An entry the CLI writes into settings.json between the settings step's last checkout and init step
  3's render (a sub-second window) is dropped at the next Stop, named by key path in the notice and
  the log; a CLI-owned key changed in that window (`model`, say) is dropped the same way (the overlay
  that exists is never rewritten).
- `hooks/auto-commit.sh`'s exit-1 path (`write_checkpoint` failing with a status other than 3) exits
  without `notice()`, so the landing notice of that Stop is lost while the home lands (log
  `result=landed`); P1's output contract for that path is kept as it is (P1).
- A landing killed between init step 3's render and step 4 leaves the home in state `hooks`, and R1
  re-runs step 5 alone there ("no other step"), so step 4's files (the TMPDIR root, the
  protected-runtime file) are not created by a later Stop; doctor reports them (review RQ-7
  reproduced it, `review-r2/rq7-after.txt`; pre-existing in round 1; for the reviewer). Its notice no
  longer says the hooks "changed" when one was missing (commit 36).
- A git-fswatch daemon whose restart fails (its new process does not start, for example a
  `hooks/git-fswatch.sh` that exits) stays stopped: the stop-and-start path kills first and starts
  after, and a failure is a notice once ("1 git-fswatch restart(s) failed") and never retried, as R8
  says; later Stops find no daemon to restart (review RQ-2, `review-r2/rq2-after.txt`; P7b, as R8
  specifies).
- In a /merge (`hooks/merge.sh`) of a home with uncommitted changes (S2, S3) the merge is refused
  and the home keeps fe7700c8's code, so no P7b code reaches it until a later pull from a clean
  tree; this is the merge rows' case (above; no phase edits merge.sh: for the reviewer).
- Sandbox kits built from `harness-repair-plan/tools/` share the host's process table when `ns.sh`
  runs alone (a mount namespace, not a PID namespace). Round 3 saw one kit's stand-in daemons gone
  while another kit and the CI suite ran (cause not isolated, UNVERIFIED). This round wraps every run
  in its own PID namespace (`work/r4/acc.sh`), and `busy`, `wedge` and acceptance 15 behaved as in
  round 2 with the CI suite running on the host; for the kit's maintainers (tools).
- A systemd unit whose `systemctl restart` fails while the old process keeps running is tried again,
  with a failure notice, at every Stop of a landed home (UNVERIFIED: no systemd here).
- The landed-home daemon check reads every `/proc/<pid>/cmdline` at each Stop: about 26 µs per
  process (28 ms at 1089 processes, `fix/evidence/scan-scale.txt`) on top of the measured overhead;
  and while a stale daemon of another harness home, or one whose repository is gone, runs, each Stop
  also takes the lock and runs the per-daemon checks, silently.
- A clone of a filter revision that later checked out a pre-P7 revision is told apart only while its
  clone entry is in the HEAD reflog (90 days by default); after the entry expires such a clone counts
  as upgraded.
- PR #4 and the official hooks documentation were not read for this PR (the earlier rounds had no
  GitHub access and no network; this round read only master's and PR #6's heads, through git): the
  semantic-diff method of acceptance 3 was rebuilt from the planning documents (normalised
  harness-home path forms, then intended = overlay env keys, enabled-module entries, and upstream
  changes the live file had not made); the Claude-process variable comes from the local CLI binary.

### Files P8 (PR #6) also touches

Both change `PUBLIC-CORE.md`, `README.md`, `hooks/lib/checkpoint-core.sh`,
`hooks/lib/subagent_restart.py` and `hooks/pretool-bash-safety.sh` (P8 also `conftest.py`,
`scripts/check-public-core.sh`, `scripts/install/installer.py`, `profiles/core.json` and
`tests/installer-acceptance.py`; it does not touch `scripts/bootstrap`,
`scripts/install/render-settings`, `scripts/install/land`, `hooks/git-hooks/`, `hooks/auto-commit.sh`,
`hooks/pull.sh` or `hooks/git-fswatch.sh`, and of its 113 deleted files none is one the landing
uses). PR #6's head 0d266922 has merged d625284 (its commit 4172e18), so both branches start from
d625284. A trial merge of this head with it (scratch repository, plain `git merge`) has no
conflict; the nine files this PR changes outside the five shared ones (eight code and test files
and `settings.machine.example.json`) are byte-identical after it (trial merge commit ba7f29b3,
detached HEAD, no branch), and every line this PR adds to the five shared files is in the merged
file (`work/evidence/review-nvf/merge-p8-trial.txt`; 760f06e7's, trial merge commit 39f9cfb3, in
`review-nv12/`; 10d7d254's, trial merge commit 2ddbdd5c, in `review-nv1v/`; 921b5128's, trial merge commit 74debc3e,
which compared seven of the nine, in `review-nv1/`; 96bcb8f2's, trial merge commit b41e3fef, in
`review-v1/`; 26a7ea7a's, 2a31f169, in `review-r4/`). On the merged tree the 117 tests pass with P8's conftest (`work/evidence/review-nvf/merged-p8-unit-a.txt`;
on 760f06e7's merge the 114, twice: `review-nv12/17-merged-p8.txt`); acceptance 1,
2, 3, 4, 6, 10 and 15, `ds`, `pullsh`, `fswatchpop` and `n1` passed in a kit built from the merge
at 98d153ad (`work/evidence-merged/`, trial merge commit d2a15c99) and were not run again.

Merge order: this PR merges first. P8 (PR #6) merges after it and must then merge `origin/master`
into `repair/P8` (a merge commit, no rebase), re-check `_checkpoint_rate_limited_push` (its hunk
starts five lines after P8's `_checkpoint_push_gate_pii_signature`) and the bash-safety prologue, and
re-run `tests/test_landing.py` and acceptance 1, 6 and 10 there. PR #6 did not deliver its optional
row 12; a hook a later change adds to bootstrap step 5 needs the line `# claude-harness <name>
(installed by scripts/bootstrap)` as its second line to be refreshed by the landing.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_017MTKKZpxjCuUDwKtkUM1j1
