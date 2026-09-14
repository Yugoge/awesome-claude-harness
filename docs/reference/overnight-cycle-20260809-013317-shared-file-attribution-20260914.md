# Attribution of unattributed content in four shared files, cycle 20260809-013317

**Date**: 2026-09-14
**Subject**: fan-out cycle `20260809-013317` (lanes `adj, doc, gitenv, guard, init,
inject, new2, tz` — overnight-loop infrastructure) has content sitting in the
`guard` and `init` lanes' `pre_edit_snapshots` / working-tree state that is not
accounted for by those two lanes' own `owned_edits` ledgers, across four
distinct files/blocks. This document determines, as precisely as the evidence
allows, who actually authored each unattributed block.
**Method**: identical to
`docs/reference/paseo-daemon-shared-file-attribution-20260913.md` — checkpoint
timestamp bisection on `refs/checkpoints/fix-dev-fanout-gatekeeper-20260717`
(git blob identity at specific auto-save instants), cross-referencing every
*other* task's own `docs/dev/*.json` artifacts (not just this cycle's 8 lanes)
for `owned_edits` entries containing matching text, and checking
vocabulary/scope/naming-convention consistency with each candidate task's own
declared work. All git object ids, line counts and grep results below were
measured directly against this repository at HEAD
`c3774fc94c63169538a9642bf55332cb5562ac57`, branch
`fix/dev-fanout-gatekeeper-20260717`. All `grep` calls were run as
`command grep` (the true `/usr/bin/grep`, bypassing this shell's
`ugrep --ignore-files` wrapper function) specifically because `docs/dev/` is
gitignored and the wrapped `grep` silently drops matches there; every "zero
matches" claim below was re-verified with `command grep` before being reported
as a negative result.

---

## Summary of the four determinations

| # | Block | Verdict | Author |
|---|---|---|---|
| 1a | `hooks/pretool-overnight-hook-guard.py`, 59 of ~165 lines: `_GOVERNING_OWN_ROOT`/`_set_governing_own_root`/`_path_targets_main` exemption + `_governing_state_for_cwd` skip | **Attributed** | task `20260809-013317`, **`guard` lane, iteration 0** (its own preserved-verbatim `iteration_history[0]`, not the top-level 6-entry ledger the dispatch pointed at) |
| 1b | `hooks/pretool-overnight-hook-guard.py`, 12 of ~165 lines: `_extract_live_worktree_path` docstring + `isolation_kind == "in_place"` exclusion | **Genuinely unattributable** | none found — predates the entire cycle |
| 1c | `hooks/pretool-overnight-hook-guard.py`, 94 of ~165 lines: `import stat`, `_state_str`, `_qa_mode_sentinel_rw_bind`, `_build_bwrap_argv` step-(8) wiring | **Attributed** | task `20260809-013317`, **`new2` lane** |
| 2 | `hooks/tests/test_overnight_qa_sentinel_bind.py` (whole file, no owner per the dispatch) | **Attributed** | task `20260809-013317`, **`new2` lane** — the dispatch's premise ("does not appear in any lane's `files_created`") is **factually wrong**; it is in `new2`'s own top-level `dev.files_created` |
| 3a | `hooks/prompt-workflow.py` — `_resolve_command_spec`/`_command_spec_candidates` refactor | **Attributed** | task `20260809-013317`, **`inject` lane** |
| 3b | `hooks/prompt-workflow.py` — `create_overnight_state` default-parameter change | **Attributed** | task `20260809-013317`, **`tz` lane** |
| 3c | `hooks/prompt-workflow.py` — delivery-receipt/fingerprint mechanism (`OVERNIGHT_EPOCH_READING`, `overnight_delivery_marker_path`, `_spec_fingerprint`, `_record_delivery_receipt`) | **Attributed** | task `20260809-013317`, **`inject` lane** |
| 3d | `hooks/prompt-workflow.py` — session-id minting logic (`sid = secrets.token_hex(16)`) | **Attributed** | task `20260809-013317`, **`tz` lane** |
| 3e | `hooks/prompt-workflow.py` — `init`'s own ledger entry 3, non-unique anchor `old = "        )\n"` (14 occurrences) | **Not misattributed** | `init`'s own edit (paired with its own adjacent entry 2); a ledger-tooling anchor defect, not content stolen from another task |
| 4 | `scripts/create-overnight-state.sh` — `ACTOR_ENV_HELPER_PATH`/`INPLACE_ENV_HELPER` fail-closed block + `GITENV_HELPER` else-branch fail-closed block | **Attributed** | task `20260809-013317`, **`adj` lane, round 1** (its own `history[0]`, not the top-level round-2 fields) |

**Cross-cutting structural finding** (applies to 1a, 1c, 3a–3d, 4): every one
of these "orphan" blocks is real, dated, first-party-documented work by
*another lane of the same cycle* — not lost work, not fabrication, and not a
different task altogether. The reason they read as orphaned from `guard`'s and
`init`'s own top-level ledgers is structural: **this cycle's dev-reports
routinely preserve only the FINAL iteration/round's `owned_edits` /
`pre_edit_snapshots` at the top level**, while earlier iterations/rounds — which
did the real, byte-verifiable work — survive only in a nested field
(`iteration_history[]` for `guard` and `init`, a bare `history[]` for `adj`, or
are simply absent from `new2`'s report structure entirely, which never had a
byte-level ledger for *any* file and relies solely on `dev.tasks_completed`
narrative + `dev.files_created`/`dev.files_modified`). A tool or reviewer that
only reads a report's top-level `owned_edits` will systematically under-count
this cycle's real authorship. See "Structural note" after item 4 below.

---

## Item 1 — `hooks/pretool-overnight-hook-guard.py` (~165 lines, blob `31ea32ea`)

### The block, precisely

`docs/dev/dev-report-20260809-013317-guard.json`'s top-level
`pre_edit_snapshots["hooks/pretool-overnight-hook-guard.py"]` =
`31ea32ea851d5c1ee7e2eed452281112eb8ef057` (2302 lines). HEAD's committed
version is 2137 lines. `diff -u` between them is 165 net added lines across 9
hunks. Replaying only `guard`'s top-level 6 `owned_edits` entries for this
file reproduces the live file (2360 lines) from the 2302-line snapshot — i.e.
the dispatch's claim that the 165-line gap predates those 6 entries is
correct. But the 165 lines are **not one block from one source** — they
decompose cleanly into three groups by hunk:

| Hunk (old line) | Δ lines | Content |
|---|---|---|
| @445 | +12 | `_extract_live_worktree_path` docstring rewrite + `in_place` early-return |
| @997 | +6 | `in_place` skip in `_governing_state_for_cwd`'s loop |
| @1320 | +49 | `_GOVERNING_OWN_ROOT` / `_set_governing_own_root` + `_path_targets_main` exemption |
| @1847 | +72 | `_state_str` + `_qa_mode_sentinel_rw_bind` |
| @21, @1870, @1911, @2026 | +1, +6, +3, +12 (=22) | `import stat` + `_build_bwrap_argv` step-(8) wiring + call site + `registry_dir` derivation |
| @2060 | +4 | `_set_governing_own_root(gov_state)` call in `main()` |

(12 + 6 + 49 + 72 + 1 + 6 + 3 + 12 + 4 = 165, exact.)

### 1a (59 lines: hunks @997, @1320, @2060) — Attributed to `guard`, iteration 0

`dev-report-20260809-013317-guard.json.iteration_history[0].report` is
`guard`'s own **preserved-verbatim** first pass (its own
`_owned_edits_history_note`: "iteration 1's maps are PRESERVED verbatim under
`owned_edits_iteration_1`" — the field is actually named `iteration_history`
in the artifact, timestamp `2026-08-20T23:03:32Z`, `baseline_head_sha
43ec4593`). Its own `pre_edit_snapshot` for this file is blob
`967a2e80c19026ae3e6479447d2d21243f9edb15` (2149 lines), and it records **3**
`owned_edits` entries for this file — distinct from the top-level 6 the
dispatch pointed at.

Byte replay: entry 0's `old` text (`def _path_targets_main(...` through the
original 5-line docstring) occurs **exactly once** in the 967a2e80 buffer;
its `new` text is the `_GOVERNING_OWN_ROOT`/`_set_governing_own_root` block
verbatim, ending in the extended `_path_targets_main` docstring — an exact
byte match for hunk @1320. Entries 1 and 2 are pure insertions (`old: ""`)
whose `new` text is byte-identical to hunks @997 and @2060 respectively.

Checkpoint corroboration, independent of the ledger: `refs/checkpoints/...`
shows `_GOVERNING_OWN_ROOT` already present at commit `27c5a3a1`
(**2026-08-20T22:42:21Z**, 21 minutes before `guard`'s own report timestamp of
23:03:32Z), part of an unbroken same-evening burst
(`27c5a3a1`→`139b6dcb`→`f0f9fd22`→`28199cd3`, 22:42:21–22:46:07) — a single
session's own incremental auto-saves while it worked, all landing before it
finished and wrote its report. `guard`'s own `ticket-20260809-013317-guard.md`
(written 2026-09-03, explicitly late and marked as such — it opens with "Done
here: recording, late and visibly marked as late, what the evidence already
establishes") independently narrates exactly this work at lines 103–109:
"Added a per-request `_GOVERNING_OWN_ROOT` plus `_set_governing_own_root
(gov_state)`... `_governing_state_for_cwd` now skips `in_place` records."

**Why this reads as orphaned from the dispatch's premise**: the dispatch
checked `guard`'s top-level 6-entry ledger (iteration 2, the 2026-09-03
QA-closure round). That ledger correctly does **not** contain this content —
because it belongs to iteration 0, whose own 3-entry ledger is a *sibling*
field (`iteration_history[0]`), not a superset of the top-level one.

### 1b (12 lines: hunk @445) — Genuinely unattributable

`_extract_live_worktree_path`'s docstring rewrite ("declare the main checkout
an isolated worktree for *every* session... imposes no boundary, which is
exactly what the user chose") and its `isolation_kind == "in_place"`
early-return are **absent from `guard`'s own iteration-0 snapshot's
predecessor state** — checked directly: checkpoint `7494263b`
(**2026-08-02T00:47:48Z**, 2137 lines) does not have it;
checkpoint `c39f5d1d` (**2026-08-08T15:53:10Z**, 2149 lines — this is
byte-identical to `guard` iteration 0's own recorded snapshot
`967a2e80`) already has it. The insertion therefore happened in the
~6-day window Aug 2–Aug 8, 2026 — **before task `20260809-013317` existed**
(its own task-id timestamp is 2026-08-09T01:33:17Z).

Narrower bracket: the one real (non-checkpoint) commit touching this file in
that window, `eed4787e` ("auto-bulk: end-of-cycle commit... hooks updates",
`Task-id: bulk`, **2026-08-07T14:15:41Z**), does **not** contain this text
either (checked both before and after that commit) — it modifies the same
file for an unrelated feature (`_get_protected_branches`/M3-RESOLUTION). So
the exact window is **2026-08-07T14:15:41Z → 2026-08-08T15:53:10Z**
(~25.5 hours), and it is uncommitted, checkpoint-only content throughout.

Exhaustive search (`command grep`, true grep, not the gitignore-filtering
wrapper) for the docstring's own distinctive phrases
(`"declare the main checkout an isolated worktree"`,
`"imposes no boundary, which is exactly"`) across all of `docs/dev/` and
`.claude/` returns **zero** matches — no task's `owned_edits`, `ticket`, or
`dev.tasks_completed` narrative anywhere claims this text. The one fan-out
cycle active in the bracket window, `20260808-035658` (dispatched
2026-08-08T03:56:58Z, lanes `laneb/lanel/lanepolcatchup/laner1salvage/
lanersgap/lanesumatdoc10/lanesuspecupdate`), lists
`hooks/pretool-overnight-hook-guard.py` only in raw `dev.files_modified`
(background baseline diff) for 2 of its 7 lanes, never in `owned_edits` — the
same "files_modified without owned_edits" non-claim shape the paseo
precedent used to rule out background noise.

**Missing evidence, stated plainly**: whichever session actually typed this
docstring between 2026-08-07T14:15:41Z and 2026-08-08T15:53:10Z left no
`docs/dev/` artifact of any kind — no ticket, no dev-report, no QA report.
Its content is real (it still stands, unaltered, in the current live file at
lines 447–464) but its author cannot be determined from any evidence this
repository retains. This is reported as unattributable per the investigation's
own rule, not guessed at.

### 1c (94 lines: hunks @21, @1847, @1870, @1911, @2026) — Attributed to `new2`

`_qa_mode_sentinel_rw_bind`'s own docstring self-identifies: `"""MID-SESSION
harness-state closure (task 20260809-013317)."""` — confirming cycle
membership, but not which lane. Resolved by content match, not just topic:

- `docs/dev/dev-report-20260809-013317-new2.json.dev.tasks_completed[0]`:
  "Added bwrap mount step (8): RW-bind the qa_mode sentinel FILE inside the
  overnight write boundary" / `changes`: "New helpers `_state_str` and
  `_qa_mode_sentinel_rw_bind`; `_build_bwrap_argv` gains an optional
  `registry_dir` param and appends step (8)..." — verbatim match to hunks
  @1847/@1870/@1911/@2026.
- `dev.tasks_completed[2]`: "Gate the qa_mode-sentinel RW bind on the
  orchestrator actor predicate, closing QA F1" / `changes`: "Two executable
  lines added as the FIRST check in `_qa_mode_sentinel_rw_bind`: `if not
  _is_orchestrator_actor(): return []`" — this is the exact `if not
  _is_orchestrator_actor()` guard present in the live function today.
- `docs/dev/qa-report-20260809-013317-new2.json` independently *executes* this
  feature end-to-end (not just reads it): `resolved_findings[0].closed_by` =
  `"hooks/pretool-overnight-hook-guard.py:1965-1966 -- \`if not
  _is_orchestrator_actor(): return []\` as the first statement of
  _qa_mode_sentinel_rw_bind"`; `success_criteria_results[0]` records
  before/after EROFS-vs-rc=0 tamper reproductions against the real bwrap
  boundary.

Checkpoint corroboration: `_qa_mode_sentinel_rw_bind` is absent at checkpoint
`8f36b1d7` (**2026-09-03T01:59:53Z**, 2255 lines) and present (1 occurrence)
at `cb99fbbc` (**2026-09-03T02:16:28Z**, 2268 lines) — a 17-minute window,
same day as `new2`'s own report timestamp (`2026-09-03T18:15:00Z`).

**Why this is absent from `new2`'s own top-level ledger too**: `new2`'s
dev-report has no `owned_edits`/`pre_edit_snapshots` fields at all, for any
file — it records only `dev.tasks_completed` narrative plus
`dev.files_created`/`dev.files_modified`. It is a structurally different
report shape from `guard`'s and `init`'s (no byte-level ledger anywhere), so
"grep for `owned_edits`" against `new2` was never going to find anything —
the dispatch's cross-check of `guard`'s ledger correctly found nothing there,
but the content's true owner (`new2`) never had a byte-level ledger to check
in the first place. First-party narrative + independent QA execution
evidence is the strongest attribution available for this block, and it is
unambiguous.

`guard`'s own `dev-report` was searched in full (every string field, not just
`owned_edits`) for any mention of `qa_mode`/`bwrap mount step`/
`sentinel_rw_bind` — **zero** hits. `guard` never discusses this content at
all, consistent with it being wholly foreign, inherited-then-untouched
content in its snapshot.

### Ruled out

- Base consolidated `docs/dev/dev-report-20260809-013317.json` (unsuffixed,
  timestamp `2026-08-09T17:11:44Z`) also narrates this exact work at
  `dev.tasks_completed[25–28]`, byte-identical to `new2`'s own report. This is
  an orchestrator-level rollup that concatenates multiple lanes' own
  `tasks_completed` arrays (task `id` numbering visibly restarts at 1 several
  times); it is not an independent source, just further corroboration that
  the content belongs to the cycle and specifically to `new2`'s numbered
  batch. Its own stale `timestamp` field (Aug 9, eleven days before the
  Sept-3 checkpoint bracket) confirms this field is not reliable for dating
  individual sub-blocks — it reflects only the base report's own initial
  creation, never updated as later content was appended.
- No other of the remaining 6 lanes (`adj, doc, gitenv, guard, init, tz`) has
  `hooks/pretool-overnight-hook-guard.py` in `owned_edits` at all; `init` and
  `new2` are the only two with it in raw `dev.files_modified` (background
  baseline diff, non-claim).

---

## Item 2 — `hooks/tests/test_overnight_qa_sentinel_bind.py`

**The dispatch's premise was checked directly and found incorrect.** The file
**does** appear in a lane's `files_created`: `new2`'s own
`dev-report-20260809-013317-new2.json`, top-level canonical field —

```
dev.files_created: ["hooks/tests/test_overnight_qa_sentinel_bind.py"]
```

— populated by `dev.tasks_completed[3]`: `{"id": 2, "type": "test",
"description": "Tracked regression suite for the previously untested binding
function.", "files_created": ["hooks/tests/test_overnight_qa_sentinel_bind.py"],
"files_modified": null}`. This is `new2`'s own regression suite for its own
`_qa_mode_sentinel_rw_bind` feature (item 1c above) — task 28 in the base
consolidated report's numbering ("Tracked regression suite for the previously
untested binding function", immediately following tasks 25–27's
`_qa_mode_sentinel_rw_bind` work).

The dispatch's own secondary observation was independently confirmed: `guard`'s
own report uses this file only as a downstream **consumer** during its own
verification —
`iteration_2.verification.direct_consumers`: `"hooks/tests/test_overnight_
qa_sentinel_bind.py + hooks/tests/test_overnight_gitenv_failclosed.py -> 44
passed, 1 skipped."`, and `iteration_2.blast_radius[0].referenced_by[5]` names
it again — i.e. `guard` *ran* this test as part of its own regression
verification (a legitimate cross-lane reuse of another lane's test asset,
since both lanes touch the same hook file), never claimed to have authored it.
A full grep of all 8 lanes' `files_created`/`files_modified`/`owned_edits`/
`pre_edit_snapshots` confirms no lane *other than* `new2` references creating
this file.

**One nuance worth recording**: `new2`'s own report separately carries a
`retroactive_correction_20260914` block (today's date), an unrelated
LAB_BASE-hardcode fix to the *same* file, which describes the file at that
later point as `"admission": "authenticated_preexisting_untracked_whole_file"`.
This is not a contradiction — "pre-existing" there is relative to *that*
Sept-14 correction pass (which needed to fix one hardcoded path, not
recreate the file), not a claim about who originally created it. The
original-authorship evidence (`dev.files_created` + the tasks_completed
narrative) is dated to `new2`'s original cycle work, not to the Sept-14 pass.

### Conclusion

**Attributed**, unambiguously, to task `20260809-013317`'s `new2` lane.

---

## Item 3 — `hooks/prompt-workflow.py` (init's two-iteration ledger gap)

### Baselines

`init`'s own report (`dev-report-20260809-013317-init.json`) has two
generations of ledger for this file:

- `iteration_history[0]` (iteration 1, own timestamp `2026-08-09T15:40:00Z`,
  own `baseline_head_sha 43ec4593`): `pre_edit_snapshots["hooks/prompt-
  workflow.py"] = 25c71656f8decb2cb41831cd6a3bc30ee4fe2bad` (1199 lines),
  2 `owned_edits` entries (adds `verify_overnight_state`).
- top level (iteration 2, own `timestamp 2026-08-20T19:29:44Z`):
  `pre_edit_snapshots["hooks/prompt-workflow.py"] = 11de18cccfb80455999ace
  10d32b127d7fd5802d` (1691 lines), 5 `owned_edits` entries (adds
  `_repair_overnight_registry`).

Checkpoint identity (exact blob match, not inference): the iteration-1
snapshot (`25c71656`) is checkpoint `2deade54`, **2026-08-08T15:52:55Z**; the
iteration-2 snapshot (`11de1866`) is checkpoint `4581933e`,
**2026-08-09T16:42:55Z** — both dated to Aug 8–9, not anywhere near the
top-level report's own stated Aug 20 timestamp. (The same
early-snapshot/late-report-write gap recurs for `scripts/create-overnight-
state.sh` below — see the Structural note.) Live file: 1941 lines.

### 3a + 3c — `_resolve_command_spec` refactor and delivery-marker mechanism → `inject`

Both are absent from `init`'s iteration-2 snapshot (0 occurrences of
`_resolve_command_spec`/`_command_spec_candidates`/`_record_delivery_receipt`;
`_spec_fingerprint` is present at 3 occurrences, already baked in as
inherited content) — i.e. neither was ever within `init`'s own 2- or 5-entry
ledgers (confirmed by reading every entry's `old`/`new` text directly; none
mentions these symbols).

`docs/dev/ticket-20260809-013317-inject.md` line 8: **"Lane: `inject`
(delivery cadence only — one issue)"** — this *is* the delivery-cadence
mechanism verbatim. Line 373 explicitly discusses `spec_fingerprint` as
inject's own S1 (Should-have) requirement, reasoned against `doc` lane editing
the same file concurrently. `docs/dev/dev-report-20260809-013317-inject.json`'s
own `owned_edits["hooks/prompt-workflow.py"]` (7 entries) modifies
`resolve_command_spec_path` — the pre-existing function that `_resolve_
command_spec`/`_command_spec_candidates` later wrap/replace (`resolve_
command_spec_path` is now a one-line delegator: `return _resolve_command_spec
(cmd_name)[0]`); `_resolve_command_spec`'s own docstring narrates fixing a
defect in exactly that prior function ("Resolving separately from reading was
a defect... the self-heal pointer sent the orchestrator to a file that does
not read, and the marker fingerprinted a file whose bytes were never sent").

Checkpoint bracket for the whole delivery-marker/refactor landing: absent at
`06e3bc97` (**2026-08-09T16:25:18Z**, 1320 lines), present at `67cc96fd`
(**2026-08-09T16:26:06Z**, 1587 lines, +267 lines in 48 seconds — one atomic
paste). This block's own comment self-dates: `"128,288 of 130,785 chars
(98.09%, measured 2026-08-09)"` — same day as the checkpoint bracket. `command
grep` across all `docs/dev/` for `OVERNIGHT_EPOCH_READING`, `overnight_
delivery_marker_path`, `_spec_fingerprint`, `_record_delivery_receipt`,
`commit_overnight_delivery` returns matches **only** in
`docs/dev/*-20260809-013317-inject.*` and its
`docs/dev/pre-edit-snapshots-20260809-013317-inject-iter2/` snapshot
directory (which literally contains
`hooks__prompt-workflow.py` and `tests__test_prompt_workflow_injection_
cadence.py` copies) — no other task anywhere in the repository.

### 3b + 3d — `create_overnight_state` default param and session-id minting → `tz`

`docs/dev/dev-report-20260809-013317-tz.json`'s own `owned_edits["hooks/
prompt-workflow.py"]` (3 entries, own `pre_edit_snapshot ff5af82a`) contains
byte-exact matches for both: entry 1's `old` text is literally `"def
create_overnight_state(end_time: str, focus: str = '', spec_path: ..."`
(the pre-change signature with `session_id: str = 'default'`); entry 2's
`new` text contains, verbatim, `"if not sid:\n    sid = secrets.token_hex
(16)"` and the "Mint it HERE rather than leaning on the launcher's own
empty-id fallback" rationale comment — an exact match to the live file's
`handle_phase_a` function. `command grep` for `"Mint it HERE rather than
leaning on the launcher"` and `"sid = secrets.token_hex(16)"` across all of
`docs/dev/` returns matches **only** in `tz`'s own dev-report and QA-report.

The comment text itself explains the functional connection back to `init`'s
own iteration-1 deliverable ("Mint it HERE... the launcher's minted id is not
returned, so `verify_overnight_state`/`_cleanup_overnight_partials` below
would resolve a different path than the record just published") —
`verify_overnight_state` is `init` iteration 1's own function — which is why
this reads plausibly as `init`'s content on first glance; it is in fact `tz`
building on top of `init`'s already-landed work, correctly, in its own
separately-ledgered edit.

### 3e — the non-unique anchor (`init`'s own top-level entry 3)

`init`'s own top-level entry 2 (`old: "        notice = (\n"`) and entry 3
(`old: "        )\n"`, `new: "        ))))\n"`) are the open- and
close-paren halves of *one* coherent edit — entry 2 rewrites the opening of a
`'\n\n'.join(filter(None, (notice, ...` expression, entry 3 closes the same
expression's extra nesting. `"        )\n"` occurs **14 times** in `init`'s
own iteration-2 snapshot (verified directly: `buf.count(old) == 14`) — a
genuine anchor-uniqueness defect in the ledger tool, the same defect class
`guard`'s own 2026-09-14 `retroactive_correction_20260914_owned_edits_repair`
block fixed for `hooks/pretool-overnight-hook-guard.py` (`EmptyOwnedOldString
Error`/non-unique-anchor). This entry is **not** duplicated or stolen from
another task's edit — its `new` text (`))))`)  has no plausible match
anywhere outside this specific `notice = (...)` expression, and it is
adjacent to, and narratively continuous with, `init`'s own entry 2. It is a
correctly-attributed edit with a poorly-chosen anchor, not a misattribution.

### Ruled out

`guard`, `doc`, `gitenv`, `new2`, `adj` have zero `owned_edits` entries for
`hooks/prompt-workflow.py` (confirmed directly); `new2` and `init` are the
only two lanes listing it in raw `dev.files_modified` without a matching
`owned_edits` entry (non-claim, consistent with shared-tree background diff).

### Conclusion

Four distinct sub-blocks, four distinct owners, **none of them `init`**:
`_resolve_command_spec`/fingerprint-marker mechanism → **`inject`**;
default-param + session-id-minting → **`tz`**. The one ledger entry that *is*
genuinely `init`'s own (the non-unique-anchor entry) is correctly attributed
to `init` and was never actually in question — it was flagged by the dispatch
as a possible sign of "misattributed/duplicated from elsewhere," which the
evidence does not support.

---

## Item 4 — `scripts/create-overnight-state.sh` (2 blocks, init's ledger gap)

### The blocks, precisely

Live file, lines 555–630: an `INPLACE_ENV_HELPER` fail-closed check ("FAIL
CLOSED. An absent/unreadable helper used to leave env_helper null and publish
anyway... `if [[ ! -f "$INPLACE_ENV_HELPER" || ! -r "$INPLACE_ENV_HELPER" ]];
then echo "Error: overnight in-place env helper missing..."`) and a
`GITENV_HELPER` `else`-branch fail-closed addition ("FAIL CLOSED — the same
fail-open one level out... `echo "Error: overnight git-env helper missing or
not executable at $GITENV_HELPER..."`).

`init`'s own iteration-1 and iteration-2 `owned_edits` for this file (2+2
entries; iteration-1 snapshot `cad4a184`, iteration-2 snapshot `24363acb`,
exact-checkpoint-matched to **2026-08-09T15:12:31Z**) neither create nor touch
either block — confirmed by reading every entry directly. `ACTOR_ENV_HELPER_
PATH` itself pre-dates the whole cycle (already 4 occurrences in the
git-committed HEAD baseline); what's new is the two *fail-closed* branches
around it.

### Attributed to `adj`, round 1

`command grep` across `docs/dev/` for the literal strings
`"overnight in-place env helper"` and `"overnight git-env helper missing"`
returns matches **only** in `docs/dev/*-20260809-013317-adj.*`. `adj`'s own
top-level report (`round: 2`) has empty/`None` `owned_edits`/`pre_edit_
snapshots` for this file — but it carries a nested `history[0]` (its own
round-1 self, timestamp **2026-09-03T07:20:00Z**, `pre_edit_snapshots
["scripts/create-overnight-state.sh"] = c7cb41c4...`), whose `owned_edits`
for this file contains **both blocks verbatim**:

- entry 0 `new`: `"    INPLACE_ENV_HELPER=...\n    # FAIL CLOSED. An
  absent/unreadable helper used to leave env_helper null and publish
  anyway..."`
- entry 1 `new`: `"else\n    # FAIL CLOSED — the same fail-open one level
  out...\n    echo \"Error: overnight git-env helper missing or not
  executable at $G..."`

`adj`'s own `dev.tasks_completed[1]`/`[2]` (inside that same `history[0]`)
narrate the identical two defects: "Guarded branch had no else. When the
helper was absent or not executable the whole branch was skipped..." and
"DEFECT ONE (in-place mode): replaced the fail-open `[[ -f
$INPLACE_ENV_HELPER ]] && ASSIGN` with an explicit refusal."

Checkpoint corroboration: both blocks land together, `b837326d`
(**2026-09-03T07:06:50Z**, +6 lines, `INPLACE_ENV_HELPER` block) immediately
followed by `f643a9f3` (**2026-09-03T07:06:56Z**, +7 lines, `GITENV_HELPER`
else block) — 6 seconds apart, one editing session — 14 minutes before `adj`
round 1's own report timestamp of `07:20:00Z`. `f643a9f3`'s blob (1070 lines)
is byte-identical to the current live file — nothing has touched this file
since.

### Ruled out

`doc`, `gitenv`, `guard`, `inject`, `new2`, `tz` all have zero `owned_edits`
entries for this file, and none appear in `dev.files_modified` either
(unlike item 3, this file is not even background-referenced by other lanes).
`gitenv` was the a-priori plausible candidate given the `GITENV_HELPER`
variable name, but its own report shows zero engagement with this file at
any level (`owned_edits` empty, `pre_edit_snapshots` `None`, absent from
`files_modified`) — the variable name is coincidental to the lane name, not
evidence of authorship.

### Conclusion

**Attributed**, unambiguously, to task `20260809-013317`'s `adj` lane, round
1 — recorded in `adj`'s own nested `history[0]`, superseded at the top level
by round 2's (different) work on this same report.

---

## Structural note: why this kept happening across items 1, 3 and 4

Three independent lanes in this cycle (`guard`, `init`, `adj`) each went
through at least two iterations/rounds of work, and in every one of the three
cases **the top-level `owned_edits`/`pre_edit_snapshots` fields describe only
the final iteration/round**, while an earlier iteration's real,
byte-replayable ledger survives only in a differently-named nested field
(`iteration_history[]` for `guard` and `init`, `history[]` for `adj`). A
fourth lane, `new2`, never had a byte-level ledger for any file at all — its
report shape relies entirely on `dev.tasks_completed` narrative plus
`dev.files_created`/`dev.files_modified`.

This means any audit — including the one this document's dispatch performed,
and the one `guard`'s own 2026-09-14 `retroactive_correction_20260914_owned_
edits_repair` performed — that checks only a report's *top-level*
`owned_edits` will under-count real authorship whenever the lane went through
more than one iteration. In three of this document's four items (1a, 1c, 3a–d,
4 — everything except the one genuinely unattributable block, 1b), the
"orphan" content was never actually missing from the repository's evidence
base; it was one field-path deeper than the top level.

`guard`'s own `gitignore_waiver` field (written today, 2026-09-14, as part of
a different, narrower record-level correction) explicitly named `hooks/
prompt-workflow.py` and `scripts/create-overnight-state.sh` as "also in-scope
for a broader repair" alongside `hooks/pretool-overnight-hook-guard.py`,
worded in a way that could be read as assuming all three gaps are `guard`'s
own malformed ledger entries. This investigation's evidence does not support
that assumption for two of the three files: the `prompt-workflow.py` gap
(item 3) resolves to `inject` and `tz`, and the `create-overnight-state.sh`
gap (item 4) resolves to `adj`. Only the `hooks/pretool-overnight-hook-
guard.py` gap is partially `guard`'s own (item 1a), and even that gap is
mixed with one block that is `new2`'s (1c) and one that is genuinely nobody's
recorded work (1b).

---

## Artifacts used

- `docs/reference/paseo-daemon-shared-file-attribution-20260913.md` (precedent
  methodology and format)
- `docs/dev/dev-report-20260809-013317.json` (base consolidated report),
  `docs/dev/dev-report-20260809-013317-{adj,doc,gitenv,guard,init,inject,new2,
  tz}.json` (all 8 lane reports, full-text and structural field inspection)
- `docs/dev/qa-report-20260809-013317-{adj,doc,gitenv,guard,init,inject,new2,
  tz}.json` (all 8 lane QA reports, targeted grep)
- `docs/dev/ticket-20260809-013317-{adj,guard,inject}.md`
- `docs/dev/pre-edit-snapshots-20260809-013317-inject-iter2/` (inject's own
  saved snapshot directory, `hooks__prompt-workflow.py` copy)
- `docs/dev/dev-report-20260808-035658{,-laneb,-lanel,-lanepolcatchup,
  -laner1salvage,-lanersgap,-lanesumatdoc10,-lanesuspecupdate}.json` (ruled
  out for item 1b's bracket window)
- `refs/checkpoints/fix-dev-fanout-gatekeeper-20260717` (full checkpoint
  history for `hooks/pretool-overnight-hook-guard.py`,
  `hooks/prompt-workflow.py`, `scripts/create-overnight-state.sh`)
- Real (non-checkpoint) commit `eed4787ed8bbe6e3e76a95c428bf00b6059984fb`
  ("auto-bulk: end-of-cycle commit... `Task-id: bulk`",
  2026-08-07T14:15:41Z)
- Live working-tree content of all three source files plus
  `hooks/tests/test_overnight_qa_sentinel_bind.py`
- `command grep` (true grep, bypassing this shell's `ugrep --ignore-files`
  wrapper) across all of `docs/dev/` and `.claude/` for every distinctive
  string cited above
