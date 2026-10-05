# Attribution-journal cutover: FLIP PLAN (Phase D, plan only)

Status: WRITTEN, NOT APPLIED. No consumer file was edited. Applying any step below is blocked by the two
preconditions in section 1.

Artifacts this plan switches to (all new, additive, tested in `hooks/tests/test_attribution_adjudicator.py`):

| Artifact | Role |
|---|---|
| `scripts/lib/attribution_adjudicator.py` (CLI wrapper `scripts/adjudicate-attribution-staging.py`) | per-file verdict: WHOLE_FILE_ELIGIBLE / SYNTHESIZED_STAGE / ENTANGLED / INSUFFICIENT_COVERAGE / NOT_TASK_FILE, plus escalation record (E1-E7) |
| `scripts/lib/attribution_aggregate_view.py` (CLI wrapper `scripts/attribution-aggregate-view.py`) | canonical-shape dev-report view from journal events + lane metadata (agent_id identity); shards demoted to narrative cross-check |
| Input contract | lane metadata JSON: `task_id`, `baseline_head_sha`, `baseline_dirty_snapshot`, `lanes[].{lane,agent_ids,shard}`, optional `baselines{path: blob}`, `foreign_agents{agent_id: task_id}` |

## 1. Preconditions (both must hold; neither holds today)

| # | Precondition | Evidence required | Status at plan time |
|---|---|---|---|
| P1 | Shadow-evidence grant. The parked scratch shadow-repository experiment needs a human grant before it may run. The grant must also name which cycles are replayed. | A recorded human grant, then a shadow report: adjudicator verdicts vs the legacy ledger route for >= 3 completed cycles, zero unexplained disagreement. | NOT GRANTED. Experiment parked. |
| P2 | Verified quiet tree: no dev cycle in flight. | All of: (a) no `docs/dev/*-<cycle>-l*.json` shard or ticket mtime newer than 30 min; (b) no live `overnight-state-*.json`; (c) no running session whose cwd is the harness checkout; (d) the journal has no event from a non-flip agent for 30 min; (e) the user confirms. | NOT VERIFIED. See section 6. |

## 2. Design decision needed before applying (plan deviation, flagged)

`scripts/aggregate-dev-report.py` validates the canonical `dev-report-<task>.json` against a projection of the
current lane shards and calls a journal-derived canonical "stale". `hooks/pretool-aggregate-check.py` also
guards canonical existence. A journal view cannot therefore be written AS the canonical without editing
`aggregate-dev-report.py` (not in the named flip set) or a hook (forbidden to agents).

Recommended: Option B, sidecar. The view is written to `docs/dev/journal-view-<task_id>.json` (never over the
canonical). The canonical keeps being produced by the shard aggregator. Consumers take ownership data from the
sidecar when `OWNERSHIP_SOURCE=journal`. This keeps the diff inside the five named consumers and makes rollback a
flag flip. Option A (`--source journal` in the aggregator) is a larger diff and is not recommended for the first flip.

## 3. Per-change diff sketch (minimal diff, flag-gated, default stays legacy)

Common switch: env `OWNERSHIP_SOURCE` in {`ledger` (default, today's behaviour), `journal`}.
Line numbers are as of plan time and will drift (sibling lanes edit these files); anchor on the quoted text.

### C1. `scripts/resolve-commit-repos.py`, ownership gate (block starting `if verify_ownership and section_name == "dev":`)

- Add a parameter `ownership_view: dict | None = None` to the plan builder; `None` keeps today's path byte-identical.
- When given, `ledger_identities` comes from `ownership_view["owned_edits"]` through the SAME
  `_canonicalized_ledger_identities` (shape is identical, so no second canonicalization path).
- New refusals, each a `PlanError` with its own code so they stay distinguishable:
  - a `files_modified` path whose verdict is ENTANGLED: code `OWNERSHIP_ENTANGLED`, message carries the escalation
    record path, scope = that path only (region-scoped; gate-side consumption of E7 is dependency D3 and is NOT built);
  - a path whose verdict is INSUFFICIENT_COVERAGE: allowed ONLY if the legacy ledger/snapshot route covers it
    (explicit `legacy_route` marker in the plan); otherwise code `OWNERSHIP_INSUFFICIENT_COVERAGE`. Never silently
    treated as owned, never silently treated as entangled.
- `files_landed_whole` dual-listing constraint is untouched.

### C2. Staging invocation path (`scripts/stage-owned-hunks.py` call sites; no change to the stager itself)

- The stager keeps replaying `--ledger` hunks onto `--snapshot`. The view already emits both in the shapes it reads
  (`owned_edits` hunks `{old,new}`; `pre_edit_snapshots` `git-blob:<sha>`), so the invocation changes only in WHERE the
  two temp files are built from (view instead of shard union).
- Pre-step per candidate: `adjudicate-attribution-staging.py --lanes <meta> --file <path>`; map verdict to action:
  WHOLE_FILE_ELIGIBLE or SYNTHESIZED_STAGE -> existing hunk route; ENTANGLED -> withhold that path, surface the
  escalation record, never stage; INSUFFICIENT_COVERAGE -> legacy route only (as C1); NOT_TASK_FILE -> skip.
- Added readback assert (extends the existing `readback_mismatch` obstacle): staged blob id == `stage_blob` /
  `stage_content_sha` from the verdict. Mismatch -> refuse and report.

### C3. `commands/commit.md`, plan construction step (the `REPOSITORY_PLAN="$(python3 ... resolve-commit-repos.py ...` call)

- Before it: when `OWNERSHIP_SOURCE=journal`, run `attribution-aggregate-view.py --lanes <meta> --output docs/dev/journal-view-$TASK_ID.json`
  (it refuses to overwrite) and pass `--ownership-view` to the resolver call.
- Add a short table mapping verdict -> action (same table as C2) and the rule that ENTANGLED withholds the path only.
- Everything else, including the repair/recheck loop text, unchanged.

### C4. `commands/close.md`, Step 0 aggregate block (the `python3 scripts/aggregate-dev-report.py --task-id "$TASK_ID"` call)

- After the existing aggregate call, in shadow mode (default): generate the sidecar view and append its
  `journal_view.disagreements` and `unresolved_files` to the close report as advisory lines. No new CLOSE verdict
  and no gate until after the validation in section 5 passes.
- When `OWNERSHIP_SOURCE=journal`: unresolved files become a finding routed through the existing
  `close_route_finding` mechanism (no new row).

### C5. `agents/changelog-analyst.md`, "Entangled-file detection (hunk-filtered staging)" section

- Replace the `check-owned-edits-entry.py` predicate (the `has_owned_edits` shell block) with the adjudicator verdict
  lookup under `OWNERSHIP_SOURCE=journal`; keep the old block under `ledger`.
- The adoption branch (`untracked_modified_adoption`) is evaluated first and stays unchanged.
- Update the exit-code interpretation text for the new refusal codes; add the "ENTANGLED is never staged" sentence.

## 4. Rollback

1. Instant: unset `OWNERSHIP_SOURCE` (or set `ledger`). All five consumers fall back to the byte-identical legacy path.
2. Code: the five edits are the only consumer diffs; `git diff` restricted to those five paths is the complete
   revert set. The new artifacts are inert without the flag and may stay.
3. Data: sidecars (`docs/dev/journal-view-*.json`) and escalation records are additive files; leaving them is harmless.
4. Verification after rollback: rerun section 5 "before" set and require the same failing-set as the recorded baseline.

## 5. Validation that must pass BEFORE and AFTER the flip

Run on a verified quiet tree. Record the "before" failing set first; the "after" set must equal it (no new node-id).

| Layer | Command (from the harness root) | Pass criterion |
|---|---|---|
| New artifacts | `python3 -m pytest -q hooks/tests/test_attribution_adjudicator.py hooks/tests/test_attribution_journal.py` | all pass (58 at plan time) |
| Consumers | `python3 -m pytest -q tests/test_commit_multi_repo_plan.py tests/test_stage_owned_hunks_boundary.py tests/test_owned_edits_ledger_contract.py tests/test_aggregate_dev_report.py tests/test_aggregate_dev_report_hook_ledger.py tests/test_aggregate_dev_report_superseded_rounds.py hooks/tests/test_changelog_analyst_declaration_categories.py hooks/tests/test_changelog_analyst_files_landed_whole_toctou.py hooks/tests/test_changelog_analyst_required_to_ship_sourcing.py hooks/tests/test_close_report_append.py` | failing set identical to recorded "before" |
| Default-run baseline | `python3 scripts/gen-test-baseline.py check` | exit 0 (no node-id absent from the baseline) |
| Shadow replay | adjudicator over >= 3 completed cycles vs the legacy route | every disagreement explained in writing; no ENTANGLED silently staged; no INSUFFICIENT_COVERAGE counted as owned |
| Live end-to-end | one real `/commit` on a throwaway cycle with `OWNERSHIP_SOURCE=journal`, then verify on BOTH desktop and mobile only if UI is touched (not here) | staged blobs equal verdict blobs; entangled path withheld with escalation record |
| After a flip | rerun the table; also `bash scripts/check-public-core.sh` residue count must not increase | equal to before |

Known pre-flip red tests are listed in the lane report (suite adjudication); they are the "before" set, not a flip regression.

## 6. In-flight status at plan time (2026-10-03, about 01:46 UTC)

- Cycle `dev-command-20261002-170011` is NOT shown quiet: shard `dev-report-...-l2.json` was rewritten at 01:29:23,
  `...-l5.json` at 01:27:42, `...-l6.json` at 01:24:49 (about 17-22 min before the check); the last journal event from a
  non-flip agent was 01:27:10 (session 496d4d98), but the 01:29 shard write is NOT in the journal (a writer the journal
  cannot see).
- Two paseo sessions with the harness checkout as cwd were `running` at 01:46.
- `.claude/overnight-state-*.json`: three files, mtimes 2026-09-14 and 2026-09-17 (stale, none live).
- `docs/dev` registry directory for the cycle: newest file 17:08 (2026-10-02).

Conclusion: P2 cannot be asserted. Do not flip.

## 7. Known limits the flip inherits

- Coverage starts at a file's first journaled event; on a real replay of the 170011 cycle's agents only 53 of 232 files
  were whole-file eligible, 152 were INSUFFICIENT_COVERAGE (76 coverage starts after the baseline, 54 unresolved
  dispatch-time baseline for dirty files, 20 tail differs from disk, 2 chain breaks), 1 ENTANGLED (ambiguous writer),
  26 not the task's. Dirty-at-dispatch files need an explicit `baselines{path: blob}` map recorded at dispatch time;
  without it the journal route cannot take them. Recording that map at dispatch is a prerequisite not covered here.
- E6 (reference `refs/pending-conflicts/` reachability) is not implemented; escalation records are JSON files only.
- E7 gate-side region scoping (dependency D3) is not implemented; C1 refuses per path, not per region.
- Ambiguous (concurrently measured) edges are conservative by design and will push shared files to ENTANGLED.
