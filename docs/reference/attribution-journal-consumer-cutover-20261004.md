# Attribution-journal consumer cutover: APPLIED (task 20261004-001927)

Status: APPLIED. Supersedes `attribution-journal-cutover-flip-plan-20261003.md`'s Option B
(flag-gated sidecar, default stays legacy) with a direct, unconditional switch: the four
callers below no longer invoke the self-reported ("replay owned_edits hunks, compare to disk")
judgment on any blocking path. The old judgment's code is untouched (deletion is a later phase).

## What changed

Every caller below now asks `scripts/lib/attribution_adjudicator.py`'s new, lane-agnostic
`ledger_structural_verdict()` / `ledger_blocks()` instead of the self-reported ledger. Without
per-task lane metadata (`scripts/lib/dispatch_metadata.py` still has no dispatcher caller — out
of scope here, same prerequisite the flip plan already named), the verdict for any given path
collapses to one of:

| Verdict | Meaning | Blocks? |
|---|---|---|
| `INSUFFICIENT_COVERAGE` (`no_journal_events`) | path predates the ledger, or was never journaled this session | No — deferred to the commit analyst's own judgment |
| `INSUFFICIENT_COVERAGE` (other reasons) | journal has edges but they do not provably reach back to the current HEAD blob | No — deferred (constraint 2: continuity within the journal's window is not proof of coverage back to the last commit) |
| `NOT_TASK_FILE` | no lane-owned edge (no lane metadata exists yet) | No — deferred |
| `ENTANGLED` (`order_not_determinable`) | the chain's own edge structure has no provable walk from the baseline — lane-agnostic, measured | **Yes** — this is the only verdict that blocks |
| `ENTANGLED` (`ambiguous_writer_decisive`) | a task-owned witness contests an ambiguous edge | Yes, once lane metadata exists (dormant today) |

A journal/git read failure is an infrastructure fault, never a verdict, and is never treated as
a conflict (disclosed to stderr where the call site has no separate fault channel; routed to
`gate_infrastructure_fault` where one already exists).

## The four call sites (plus the ones that cascade from one of them)

| # | Call site | Old authority | New authority |
|---|---|---|---|
| 1 | `scripts/aggregate-dev-report.py::_completeness_check_file`, `require_full_coverage=False` branch (the `same_cycle_only=True` / `OWNERSHIP_COMPLETENESS_BLOCKING_KEY` gate) | `stage-owned-hunks.py::_replay_with_provenance` combinatorics | `ledger_structural_verdict()` |
| 2 | Every OTHER caller of `_apply_completeness_check(..., same_cycle_only=True)` — `scripts/resolve-dev-artifact-chain.py`'s `OWNERSHIP_COMPLETENESS_GAP` error (reached from `/close` and from `scripts/close-route-select.py`, `scripts/late-repair-controller.py`, `scripts/dev-lifecycle.py`, `hooks/stop-completion-gate.py`, all of which load `resolve-dev-artifact-chain.py`) | same as #1 | same fix as #1 — one shared function, cascades for free |
| 3 | `hooks/subagentstop-artifact-contract-enforce.py`'s artifact-contract section (`_wire_ledger` + `_wire_stager_replay`, now replaced by `_wire_ledger_judgment`) | `check-owned-edits-ledger.py` (subprocess) + `stage-owned-hunks.py --dry-run` (subprocess) | `ledger_structural_verdict()` per `dev.files_modified ∪ dev.files_created` |
| 4 | `scripts/resolve-commit-repos.py::build_plan`'s ownership gate (`_ledger_entangled()`) | self-reported `owned_edits` / `baseline_dirty_snapshot` / `files_landed_whole` identity presence | the self-report computation narrows the candidate set (kept, unchanged); the actual raise now requires `ledger_blocks()` on the narrowed candidates |

No fifth live entry point was found; `scripts/check-owned-edits-ledger.py` and
`scripts/stage-owned-hunks.py --ledger/--snapshot/--dry-run` keep their code (next phase deletes
it) but have zero remaining blocking callers after this cutover.

## Real callers for the two previously-dead modules

- `scripts/lib/attribution_adjudicator.py` — now called (as `ledger_structural_verdict`/
  `ledger_blocks`) from all four sites above. Its full per-task API (`adjudicate_file`,
  `adjudicate_task`, lane metadata) remains additive until dispatch-time capture is wired.
- `scripts/lib/attribution_aggregate_view.py` — now called from
  `hooks/subagentstop-artifact-contract-enforce.py::_write_journal_view_sidecar`, best-effort and
  non-blocking, writing `docs/dev/journal-view-<task_id>.json` (refuses to overwrite) on every
  dev-report SubagentStop.

## What this does NOT prove

A `WHOLE_FILE_ELIGIBLE` / `SYNTHESIZED_STAGE` verdict never fires from these four call sites today
(no dispatch-time baseline capture exists), and chain continuity + a tail match only prove the
journal's own window is self-consistent — never that it covers every byte back to the last commit.
No output text from this cutover may read as "fully attributed"; the honest claim is "no measured
conflict."

## Verification

```
python3 -m pytest -q tests/test_commit_multi_repo_plan.py tests/test_aggregate_dev_report.py \
  tests/test_aggregate_dev_report_hook_ledger.py tests/test_aggregate_dev_report_superseded_rounds.py \
  tests/test_resolve_dev_artifact_chain.py tests/test_completeness_channel_invariant.py \
  hooks/tests/test_artifact_contract_enforce.py hooks/tests/test_attribution_adjudicator.py \
  hooks/tests/test_attribution_journal.py
```

Known pre-existing failure, not from this cutover: `tests/test_completeness_channel_invariant.py
::test_both_halves_call_one_implementation` — `scripts/resolve-dev-artifact-chain.py` carries a
second, uncommitted `aggregate._apply_completeness_check(` call site from another in-flight
session's dirty working tree (561 uncommitted lines on that file at the time of this cutover,
none of them written by this task).
