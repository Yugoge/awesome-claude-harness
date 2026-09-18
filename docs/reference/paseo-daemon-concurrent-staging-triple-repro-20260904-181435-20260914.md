# Triple, independent reproduction of the shared-file concurrent-staging defect

**Task-id**: `20260904-181435` (fan-out lanes a+b, "wake-channel reliability
hardening")
**Date**: 2026-09-14
**Purpose**: evidentiary record for a spec that will make "clean pure-insertion
interleaving" and "genuinely interleaved/order-dependent interleaving" between
concurrent tasks on one shared file a properly-supported first-class case. This
document consolidates three independent reproductions — different mechanisms,
same three shared files, same underlying defect — for that spec to cite. It
does **not** propose a fix or design.

All git object ids, line counts, and command output below were measured
directly against this repository at HEAD `4b90034884e1ffd7c84b55bf69e7c6b2d74c404a`,
branch `fix/dev-fanout-gatekeeper-20260717`, on 2026-09-14. The three shared
files are `scripts/paseo-daemon-ledger.py`, `commands/paseo-daemon.md`,
`tests/test_paseo_daemon_ledger.py`. Scratch artifacts used to build and run
the reproductions below are held at
`/tmp/scratch-holding-20260913/path1-repro/` and
`/tmp/scratch-holding-20260913/path3-repro/` for re-verification; nothing was
staged or committed in the real repository in the course of this
investigation (verified by `git diff --cached` before/after every command; one
"real-index" mode was rehearsed only inside a disposable `git clone`, never
against the working repository).

---

## Path 1 — plain `--ledger`/`--snapshot` staging mode

**Mechanism**: `scripts/stage-owned-hunks.py`'s plain live-provenance mode
(`--ledger <edits.json> --snapshot <pre-edit-bytes>`). It replays a task's
`{old,new}` edit list forward from the snapshot and requires the final
replayed buffer to be **byte-identical to the current worktree file**; if any
`old` string is not uniquely locatable at its step, or the final replay
doesn't match the worktree, the **entire file** is excluded — there is no
partial/per-entry success path in this mode (confirmed by direct code
reading of `scripts/stage-owned-hunks.py:1409-1433`, `_locate_unique`/`replay
!= worktree` both `return _excluded(...)` immediately, aborting the loop).

**What the task brief claimed**: lane a's 12 `owned_edits` entries for
`scripts/paseo-daemon-ledger.py` staged 8-of-12 successfully, 4 excluded for
depending on the ~419 unattributed lines later attributed (in
`paseo-daemon-shared-file-attribution-20260913.md`) to tasks
`20260831-031316`/`20260831-150938`.

**What I verified, and where the claim does not hold up**:

- **The "12 entries" figure does not belong to lane a of `20260904-181435`.**
  `docs/dev/dev-report-20260904-181435-a.json`'s `owned_edits` for
  `scripts/paseo-daemon-ledger.py` currently has **24** entries (post a
  2026-09-13 repair, `owned_edits_record_repair_20260913.before_after`,
  that overwrote a prior **35**-entry array — 9 of which had an empty `old`
  string and were immediately non-replayable: `"FAIL at edit 0: old ('')
  occurs 75839 times"`). Neither 35 nor 24 is 12. The actual 12-entry ledger
  for this file belongs to a **different, earlier task**,
  `20260831-031316` (`docs/dev/dev-report-20260831-031316.json`,
  `owned_edits["scripts/paseo-daemon-ledger.py"]`, length 12 — confirmed by
  direct read) — the same task documented in Window 1/Layer 1 of
  `paseo-daemon-shared-file-attribution-20260913.md`. I could find no
  on-disk artifact (scratch file, dev-registry log, codex-consult
  transcript, or paseo-daemon inbox finding) recording an "8 of 12
  succeeded" staging attempt for either the 12-entry (031316) or the
  24/35-entry (lane a) ledger.
- **The claimed result shape ("8 succeeded, 4 excluded") is not one this
  code path can produce.** I reproduced the mode directly, twice, and both
  runs returned a single whole-file EXCLUDE, not a partial count:
  1. Real repository, lane a's current 24-entry ledger
     (`--ledger ledger-a-current-24.json`) against real committed HEAD
     content as the snapshot (`--snapshot head-snapshot.py`, blob
     `648329fbdc34104fe24c0f4007f5850ec9f45fa3`, 1252 lines):
     ```
     EXCLUDE (fail-closed): owned old_string for edit 1 not uniquely
     locatable during replay (absent or duplicated at this step) ->
     ambiguous: scripts/paseo-daemon-ledger.py
     ```
     exit code 10, failing at edit **1** of 24 — immediately, not after 8
     successes. `git diff --cached` before and after: empty both times (no
     side effect on the real index).
  2. A disposable `git clone` of this repository (never the live working
     tree), using task `20260831-031316`'s own genuine 12-entry ledger and
     its own genuinely-correct snapshot (its recorded `pre_edit_snapshot`
     `648329fb...`, byte-identical to real HEAD — confirmed via
     `git cat-file -p`), run against the clone's current live worktree
     content (2413 lines, everything every later task added):
     ```
     EXCLUDE (fail-closed): replayed owned edits do not reproduce the
     worktree (unattributed peer edit or ledger inconsistency detected)
     for scripts/paseo-daemon-ledger.py
     ```
     exit code 10 — again one whole-file EXCLUDE, for the structurally
     inevitable reason that the live worktree now also contains lane
     b's, `20260831-150938`'s, and `20260911-011102`'s later layers on
     top of `031316`'s own 12 edits, which this mode requires to be
     fully absent for a match.

**Why this still corroborates the underlying defect, independent of the
arithmetic**: both runs above independently confirm the qualitative claim —
this mode cannot stage a task's own legitimate edits to this file when other
concurrent/adjacent tasks' content is baked into the same file, whether the
mismatch is against a too-early baseline (run 1: real HEAD lacks the 419
wake-channel lines lane a's ledger already assumes) or a too-late one (run 2:
the live worktree has more layered content than the 12-entry ledger alone
accounts for). The reason given in the task brief (~419 unattributed lines
not present in real committed HEAD) is real and independently confirmed:
`git show HEAD:scripts/paseo-daemon-ledger.py` is 1252 lines
(`648329fb...`), while lane a's actual recorded `pre_edit_snapshot` is 1666
lines (`cad35d89...`, confirmed present via `git cat-file -t`) — a 414-line
gap consistent with the "~419 unattributed lines" figure and with
`paseo-daemon-shared-file-attribution-20260913.md`'s own diff measurement.
What does **not** hold up is the specific "12 entries / 8 succeeded / 4
excluded" partial-success framing: it misattributes a 12-entry ledger that
belongs to a different task, and it describes an outcome shape (partial
per-entry success within one file) that this tool mode is structurally
incapable of producing.

---

## Path 2 — checkpoint-provenance reconstruction

**Mechanism**: `refs/checkpoints/fix-dev-fanout-gatekeeper-20260717` checkpoint
history (git blob identity at specific auto-save instants), combined with
byte-level replay of each candidate task's own recorded `owned_edits` against
an independently-existing checkpoint blob. Fully documented in
`docs/reference/paseo-daemon-shared-file-attribution-20260913.md`; not
repeated here in full, only spot-verified and extended.

**Spot-verification performed today**: re-derived, independently of the
existing document's narrative, that `git show HEAD:scripts/paseo-daemon-ledger.py`
is exactly 1252 lines and hashes to blob `648329fbdc34104fe24c0f4007f5850ec9f45fa3`
— which is *also* task `20260831-031316`'s own recorded `pre_edit_snapshot`
for this file, confirming the document's claim that this file has had zero
real commits since that snapshot. Re-derived that blob `cad35d8930e747e0c5900e0d1beeb5a1f2836e1d`
(lane a's `pre_edit_snapshot`) is 1666 lines, and that replaying task
`20260831-031316`'s own 12 `owned_edits` entries onto `648329fb...` produces a
diff of 336 added / 5 removed lines (net +331, 1252 → 1583), landing on blob
`e60173b6a7effab3d492747e77916e198efe86a6` — all matching the existing
document's figures exactly. Current live worktree content for all three files
(575 / 2413 / 3556 lines for `.md` / ledger.py / test file respectively) also
matches the document's claimed current-live line counts exactly.

**New corroboration found today, extending the document's own "forensic
reconstruction ≠ live stageability" gap**: Path 1's clone experiment above
(run 2) is itself an independent, freshly-produced instance of exactly the
gap `paseo-daemon-shared-file-attribution-20260913.md` reports having hit in
"a later /commit dispatch this same session" — using task `20260831-031316`'s
own byte-verified, checkpoint-corroborated 12-entry ledger and its own
genuinely-correct snapshot, staging still fails against the real live
worktree, for the structural reason that later tasks' content now sits
adjacent to it in the same file. This was reproduced today via a different
route (a fresh `--ledger`/`--snapshot` invocation in a disposable clone, not
a repeat of whatever the original `/commit` dispatch did) and lands on the
same conclusion.

**Independent corroboration**: different mechanism (checkpoint-history
diffing + `pre_edit_snapshot` replay against real git objects, rather than a
staging-tool invocation), same three files, same conclusion — this task's
own legitimate, byte-verifiable content cannot be cleanly separated from
adjacent concurrent tasks' content in the same file by any means tried so
far, even when the content's authorship is not in question.

---

## Path 3 — `--provenance-plan --plan-only` hunk-composability check

**Mechanism**: `scripts/stage-owned-hunks.py --provenance-plan <plan.json>
--task-id <id> --plan-only`, which composes one or more ordered "live"
provenance segments (each a `{pre_edit_snapshot, owned_edits}` pair) into a
single patch, then iteratively intersects two independent facts hunk-by-hunk
— composability against a clean index copy of real HEAD, and reversibility
against the real current worktree — keeping only hunks that satisfy both.
`--plan-only` operates on a temporary copy of the git index
(`GIT_INDEX_FILE` redirected to a tempdir), so it cannot mutate the real
repository; verified empty `git diff --cached` before and after every run
below.

**Exact reproduction performed today**: built one provenance plan per shared
file, using *only* this task's own lane-a-then-lane-b `owned_edits`/
`pre_edit_snapshots` from `docs/dev/dev-report-20260904-181435-a.json` and
`-b.json` (no foreign task content fed in at all). Confirmed first that the
two lanes chain cleanly: replaying lane a's own edits onto its own snapshot
reproduces lane b's declared snapshot byte-for-byte for all three files
(`scripts/paseo-daemon-ledger.py`: `cad35d89...` → `ec63c6cf...`;
`commands/paseo-daemon.md`: `66fc957d...` → `973ed635...`;
`tests/test_paseo_daemon_ledger.py`: `4a2f283f...` → `179dc25c...`) — i.e.
lanes a and b are each internally consistent and mutually consistent with
each other; only the interaction with *other* tasks' adjacent content in
the same files is what fails below. Ran against real HEAD
(`4b900348...`) with `--plan-only`:

- **`commands/paseo-daemon.md`**: `EXCLUDE (fail-closed): no provenance hunk
  is both index-composable and current-reversible`, exit 10. **Zero** of
  this task's hunks composed.
- **`scripts/paseo-daemon-ledger.py`**: exit 0, but only **1 of 46** hunks
  (`live_hunks_excluded: 45`) survived — a 2-line fragment adding
  `import secrets` / `import subprocess`.
- **`tests/test_paseo_daemon_ledger.py`**: exit 0, but only **2 of 60**
  hunks (`live_hunks_excluded: 58`) survived — one hunk widening `run()`'s
  signature with an `env=` parameter, and one hunk adding three small helper
  stubs (`wake_record`, `put_wake_record`, `set_config`).

This exactly reproduces the result the task brief attributed to today's
earlier changelog-analyst dispatch, independently re-derived from the raw
ledger data rather than taken on trust.

**Independent corroboration**: a third, structurally distinct mechanism
(ordered per-hunk composability filtering against a scratch git index, run
to convergence) — as opposed to Path 1's whole-file replay-must-equal-
worktree check, or Path 2's checkpoint-blob diffing — applied to the *same*
task's *own* legitimate, internally-consistent, two-lane-chained ledger data
for the *same* three files, and it lands on the same qualitative outcome:
this task's substantial own work (419+ lines across three files) is almost
entirely non-separable from the shared files' current state, surviving only
as small, contextually-isolated fragments (or nothing at all, for the `.md`
file).

---

## Synthesis

All three paths — a whole-file forward-replay check, checkpoint-history
diffing, and per-hunk composability filtering — independently agree that:
(1) the defect is real, not an artifact of one tool's bug (three structurally
different mechanisms hit it); (2) it reproduces consistently against the same
three shared files under real, current repository state, today; and (3) the
task's own content is legitimate and byte-verifiable (its authorship is not
in question in any of the three paths) yet still cannot be isolated and
staged separately from other concurrent/adjacent tasks' content in the same
file. What remains unresolved: of the three sanctioned mechanisms exercised
here — plain `--ledger`/`--snapshot` replay, checkpoint-provenance
reconstruction, and `--provenance-plan` hunk composition — none can stage
this task's genuinely-owned, internally-consistent content in isolation when
it depends on immediately-adjacent, already-existing changes from other
concurrent tasks in the same file. `--provenance-plan` gets closest (it does
salvage small, truly-isolated fragments rather than failing the whole file),
but even it drops the overwhelming majority of this task's own work (0/1,
1/46, and 2/60 hunks survived across the three files) and cannot recover the
rest without a mechanism this investigation did not find.

One correction to carry into the spec: the "12 entries / 8-succeeded /
4-excluded" figure that motivated documenting Path 1 does not describe lane
a of `20260904-181435` — that specific 12-entry ledger belongs to task
`20260831-031316` — and the "8 of 12" partial-success shape does not match
how `--ledger`/`--snapshot` mode actually fails (a single whole-file
EXCLUDE, confirmed by two fresh reproductions above). The qualitative defect
Path 1 was invoked to illustrate is nonetheless real and independently
reproduced twice today by direct experiment; only the specific arithmetic
attributed to it should not be cited as-is.
