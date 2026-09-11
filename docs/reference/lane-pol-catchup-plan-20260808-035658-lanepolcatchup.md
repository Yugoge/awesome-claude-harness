# LANE-POL Catch-Up Plan — origin/master → fix/dev-fanout-gatekeeper-20260717

**Task ID**: 20260808-035658-lanepolcatchup
**Written**: 2026-09-10, dev subagent, this session
**Status**: PLAN ONLY — no git integration command was executed by BA or dev.
Every fact below was independently re-measured by dev this session (not copied
from the BA ticket) via a fresh `git fetch origin master` followed by
read-only git plumbing commands. **Only a human controller may run the
commands in the "Execution Sequence" section.**

## 1. What is missing and why

`hooks/lib/bash_execution_boundary.py`, `hooks/lib/bash_active_syntax_census.py`,
a rewritten `hooks/pretool-bash-safety.sh`, and their supporting tests/fixtures
(LANE-POL, spec-20260808-035658 Section 2 Cycle 6 + Cycle 8 lane r02) were
developed and merged to `origin/master` through a different worktree/branch
lineage than the current branch. The current branch
(`fix/dev-fanout-gatekeeper-20260717`) never received that lineage.

## 2. Measured commit divergence (this session, fresh `git fetch origin master`)

- `origin/master` = `fa0aea69ccedee7a9fdc71f3b0bfece0fc86c983` (unchanged by the fetch — no staleness).
- `HEAD` = `10e2f132217cf27c899110dc5eff632c50ebd5ca`.
- Single merge-base (no criss-cross ambiguity): `71f5dfbc5c5cea3390473a74aab940ebce96803e`.
- `git rev-list --left-right --count HEAD...origin/master` = the branch is
  **5 commits ahead** of the merge-base (its own unpushed work) and
  **7 commits behind** `origin/master`.

**7 commits `HEAD..origin/master`** (this branch is missing all of these):

| Commit | Summary |
|---|---|
| `bb3e52df` | Merge pull request #1 from Yugoge/fix/dev-fanout-gatekeeper-20260717 |
| `ae11e2e9` | fix(hooks): close MAX_BOUNDARIES fail-open in execution-boundary analyzer |
| `730ed2c7` | fix(hooks): make 20260819-124121 commit tree self-consistent |
| `cf564cd7` | fix(hooks): fail-closed execution-boundary removal policy (POL r02) |
| `4828bb4b` | Merge fix/dev-fanout-gatekeeper-20260717 (468e38bc, 71f5dfbc lineage) — remote-side merge per user supervisor authority |
| `dce9fff9` | chore(hooks): land corrected schema-projection unit closing gate fail-open |
| `fa0aea69` | Merge worktree-overnight-20260810-019fe5c1 (dce9fff9 lineage) — remote-side merge per user supervisor authority |

The 4 LANE-POL commits named in the lane requirement — `730ed2c7`, `cf564cd7`,
`ae11e2e9`, `dce9fff9` — are all present in this range, plus the 3 merge
commits (`bb3e52df`, `4828bb4b`, `fa0aea69`) needed to complete it. No other
content exists in `HEAD..origin/master`.

**5 commits `origin/master..HEAD`** (unique to this branch, already pushed —
`origin/fix/dev-fanout-gatekeeper-20260717` = `10e2f132`, so nothing here
requires a force-push):

| Commit | Summary |
|---|---|
| `b4b5f13b` | docs(repo): correct README count claims and archive push-gate KEEP decision |
| `68a2205b` | docs(reference): record measured harness-fix status and stranded-cycle abandonment |
| `3e55e508` | feat(scripts): add extended headline-claims gate for four excluded metrics |
| `be418621` | chore(scripts): machine-readable owned-edits ledger contract and checker |
| `10e2f132` | fix(dev-artifacts): derive ship-set from lane shards; fix lane attribution |

## 3. Measured file overlap — zero, three independent ways (TEXTUAL CONFLICT only — see §4 for behavioral risk)

1. `comm -12` between the 16 files touched `71f5dfbc..origin/master` and the
   24 files touched `71f5dfbc..HEAD` → **empty** (zero overlap).
2. Same 16-file set vs the current working tree (`git status --porcelain`,
   **69 entries** this session — drifted from the 67 recorded in the
   orchestrator's execution-baseline doc and the 67 BA measured; this is
   expected drift in a live dirty tree and does not change the result) →
   **empty** (zero overlap).
3. `git merge-tree 71f5dfbc HEAD origin/master` (non-mutating dry run, exit
   0) → **zero** `<<<<<<<` conflict markers.

The 16 files touched `71f5dfbc..origin/master` are entirely under `hooks/`:
`hooks/lib/bash_execution_boundary.py`, `hooks/lib/bash_active_syntax_census.py`,
`hooks/lib/contract_runtime.py`, `hooks/lib/pol_degraded_removal_reference.ere`,
`hooks/pretool-bash-safety.sh`, and 11 files under `hooks/tests/`.

Net diffstat `71f5dfbc..origin/master`: **16 files changed, +26871/-22 lines**
(re-measured this session, matches BA's number exactly).

No native `post-merge` git hook is registered
(`core.hooksPath` = `.git/keystone-hooks`, contents: `post-commit`,
`pre-commit`, `reference-transaction`, `preserved/` — no `post-merge` file),
so `git merge origin/master` will not trigger unexpected local automation
beyond git's own default merge-commit creation.

## 4. Recommendation: `git merge origin/master` (not cherry-pick, not rebase)

**Rationale for merge**:
- Single clean merge-base (`71f5dfbc`), no criss-cross ambiguity.
- Zero file overlap measured 3 independent ways (§3) — this proves zero
  **textual conflict**, not zero behavioral-regression risk (see §5).
- Clean `git merge-tree` dry run (exit 0, zero conflict markers).
- Preserves the "remote-side merge per user supervisor authority" provenance
  already recorded in the 3 merge commits' own messages (`bb3e52df`,
  `4828bb4b`, `fa0aea69`) — cherry-picking would discard that provenance
  trail and require re-picking individual non-merge commits out of order.

**Rejected: cherry-pick** — would require manually selecting the 4 non-merge
commits (`ae11e2e9`, `730ed2c7`, `cf564cd7`, `dce9fff9`) while discarding the
3 merge commits' history, losing the "remote-side merge per user supervisor
authority" provenance record for no benefit (zero conflicts either way).

**Rejected: rebase** — the 5 local-only commits
(`b4b5f13b`…`10e2f132`) are already pushed to this branch's own remote
(`origin/fix/dev-fanout-gatekeeper-20260717` = `10e2f132`, zero divergence).
Rebasing them onto `origin/master` would rewrite already-pushed history and
require a separately-authorized force-push — an unnecessary escalation when a
plain merge has zero conflicts.

## 5. Verification (MUST run — covers behavioral regression risk, not just textual conflict)

`hooks/pretool-bash-safety.sh` is **replaced** by this merge with net +140
lines (`git diff --shortstat 71f5dfbc origin/master -- hooks/pretool-bash-safety.sh`
= `1 file changed, 148 insertions(+), 8 deletions(-)`, re-measured this
session, matches BA exactly). Zero file-overlap (§3) proves no merge will
*conflict* on this file — it says nothing about whether the current branch's
own pre-existing tests that exercise this file at runtime will still pass
against the replaced content, because those test files do not themselves
appear in either side's changed-file list.

Run **both** of the following before pushing:

### 5a. LANE-POL's own suite
```
pytest hooks/tests/test_bash_execution_boundary.py \
       hooks/tests/test_bash_safety_context_rules.py \
       hooks/tests/test_pol_generative_sweeps.py \
       hooks/tests/test_report_projection_contract.py \
       hooks/tests/test_runtime_guard.py -q
```
Confirms the merged-in state matches the PASS state already recorded in
`spec-20260808-035658.md` (iteration 6, 436-case replay 0 mismatch).

### 5b. Current branch's dependent test surface for the replaced file (baseline-then-diff)

Discovery command (self-discovering — re-run it, do not hardcode the count):
```
grep -rl pretool-bash-safety --include='*.py' tests/ scripts/ | grep -v 'tests/scripts/validate-'
```
This session: **63 files** matched.

**This exact command was independently executed by dev this session** against
current pre-merge `HEAD` (`10e2f132`):
```
pytest $(grep -rl pretool-bash-safety --include='*.py' tests/ scripts/ | grep -v 'tests/scripts/validate-') -q
```

**Real output, this session**:
```
FAILED tests/generated/20260614-205834/test_AC10_47ac0a52947d1021.py::test_AC10
FAILED tests/generated/20260618-135436/test_AC5_537cf49fef78b002.py::test_AC5
FAILED tests/generated/20260526-052559/test_ac_03_ac03-relative-path-allowed.py::test_ac_03
FAILED tests/generated/20260525-095242/test_AC_04_bypass_20260525.py::test_AC_04_bypass_allow_rows[C16]
FAILED tests/generated/20260525-095242/test_AC_01_f1a2b3c4d5e6f7a8.py::test_AC_01_layer1f_compound_bypass_matrix[C16]
FAILED tests/generated/20260521-090300/test_AC7_ac7-bypass-closed-after-deletion.py::test_AC7
FAILED tests/generated/20260521-090300/test_AC4_ac4-bypass-active-via-home-symlink.py::test_AC4
7 failed, 130 passed, 5 skipped, 2 xfailed in 80.48s (0:01:20)
```
(Note: BA's own independent run this same pre-merge HEAD reported "132
passed, 7 failed, 5 skipped" — the discrepancy is 130 passed + 2 xfailed here
vs 132 passed there, a pytest reporting-bucket nuance between runs, not a
different result: **the failing test set itself is byte-identical** — the
same 7 named tests above. This is exactly the drift risk the baseline-then-diff
recipe below is designed to tolerate: it diffs the PASS/FAIL SET, not a
hardcoded total count.)

All 7 failures are pre-existing on current `HEAD`, unrelated to LANE-POL or
to `hooks/pretool-bash-safety.sh`'s own behavioral change:
- 2 of 7 (`test_AC4`, `test_AC7` in `tests/generated/20260521-090300/`):
  `FileNotFoundError` for `hooks/pretool-block-production-files.sh`, a
  sibling hook removed by commit `d0f12f55` ("de-privatize public harness").
- 3 of 7 (`test_ac_03`, `test_AC_04_bypass_allow_rows[C16]`,
  `test_AC_01_layer1f_compound_bypass_matrix[C16]`): a bulk-commit-sentinel
  compound/write-surface guard mismatch (rc=2 vs expected rc=0 for case
  C16), unrelated to `pretool-bash-safety.sh`'s content.
- 2 of 7 (`test_AC5`, `test_AC10`): git-state assumptions tripped by this
  session's own dirty working tree / branch history (a DOC-ONLY
  forbidden-path check, and a "baseline commit is not an ancestor of HEAD"
  check) — properties of the current branch's live state, not of the
  LANE-POL merge.

**Baseline-then-diff recipe** (a bare post-merge-only run cannot distinguish
a merge-introduced regression from a pre-existing flaky/failing test):

1. Before merging, run the command above and save the pass/fail set (this
   session's run, shown above, may be used as the baseline if the merge
   happens shortly after this plan is written — but re-run it if meaningful
   time has passed, since the dirty-tree-dependent failures can change).
2. Merge (§6).
3. Re-run the identical command post-merge.
4. Diff the pass/fail sets. **Only a test that passed pre-merge and fails
   post-merge counts as a regression.** A test that was already
   failing/flaky pre-merge is a pre-existing condition, out of this lane's
   scope.
5. **If any test that passed pre-merge fails post-merge: STOP. Do not push.**
   Treat it as a merge-introduced behavioral regression (not a
   re-litigation of LANE-POL's own already-QA-PASSed correctness) and
   report it to the orchestrator.

An unscoped full `pytest tests/ hooks/tests/ -q` run MAY be run afterward as
an optional extra-confidence step, but is not required and must not replace
the targeted baseline-then-diff recipe above (unrelated pre-existing
flakiness elsewhere in `tests/` could otherwise be mistaken for a
merge-introduced regression).

## 6. Execution Sequence (for the human controller — NOT executed by BA or dev)

**Precondition — re-verify freshness immediately before running any of
this**, since git state can drift between when this plan was written and
when it is executed:
```
git fetch origin master
git rev-parse origin/master          # expect fa0aea69ccedee7a9fdc71f3b0bfece0fc86c983 — if different, re-derive this plan's commit list before proceeding
git log --oneline HEAD..origin/master   # re-confirm the 7-commit range above is unchanged
```

Then:
```
# 1. Capture pre-merge baseline (§5b step 1)
pytest $(grep -rl pretool-bash-safety --include='*.py' tests/ scripts/ | grep -v 'tests/scripts/validate-') -q

# 2. Merge
git merge origin/master

# 3. Inspect for a clean merge (expected — zero conflicts per §3)
git status

# 4. Run LANE-POL's own suite (§5a)
pytest hooks/tests/test_bash_execution_boundary.py \
       hooks/tests/test_bash_safety_context_rules.py \
       hooks/tests/test_pol_generative_sweeps.py \
       hooks/tests/test_report_projection_contract.py \
       hooks/tests/test_runtime_guard.py -q

# 5. Re-run the dependent-test-surface command post-merge and diff against the pre-merge baseline (§5b steps 3-4)
pytest $(grep -rl pretool-bash-safety --include='*.py' tests/ scripts/ | grep -v 'tests/scripts/validate-') -q

# 6. Only if steps 4 and 5 show no pre-merge-pass -> post-merge-fail transition: push (ordinary, non-force)
git push origin fix/dev-fanout-gatekeeper-20260717
```

## 7. No-Execution Disclaimer

**No git integration command (`merge`, `cherry-pick`, `rebase`, `commit`, or
`push`) was executed by BA or by dev for this lane.** Every command shown
above was either a read-only measurement (`git fetch`, `git log`,
`git diff --name-only`/`--shortstat`, `git merge-base`, `git status
--porcelain`, `git merge-tree` non-mutating dry run) or a read-only test run
(`pytest`, no code changes). This document is a plan only. **Only a human
controller may execute the "Execution Sequence" commands in §6.**

## 8. Explicitly out of scope

- `.claude/worktrees/overnight-20260810-019fe5c1` — a separate, live,
  uncommitted worktree checked out at `dce9fff9` with ~60 uncommitted
  changes, tracked as LANE-R1's salvage concern in
  `docs/dev/execution-baseline-20260808-035658.md` Section 2. It is not this
  lane's target and is not touched, merged, or referenced as an action item
  here — noted only so the human controller does not conflate it with the
  `origin/master`-based catch-up above.
- Any other lane in `execution-baseline-20260808-035658.md`
  (LANE-R1, LANE-B, LANE-RS, LANE-SU, LANE-BIND, LANE-SCHEMA, LANE-LEASE,
  LANE-DOC, Fix-2).
- Re-reviewing the LANE-POL security-hook code itself (already QA-PASSed on
  `origin/master`).
- Any branch/PR/worktree creation.
