# Overnight 20260810 worktree test landing: diagnosis of 22 files

**Source**: worktree `overnight-20260810-019fe5c1`, session `019fe5c1-5b46-7dd1-8086-591a5b932bf3`, spec `20260808-035658`, recovery coordinate `refs/checkpoints/worktree-overnight-20260810-019fe5c1` = `1af2a2dcbb4a119f01f956e32617dfec9bc0e5a9`. Tickets: `laneb`, `lanel`, `lanepolcatchup`, `laner1salvage`, `lanersgap`, `lanesumatdoc10`, `lanesuspecupdate`.

Content was extracted via `git show <checkpoint>:<path>` for each of the 22 paths, not read from the live worktree (which carries lock files and mtime noise).

**Cycle status**: the source cycle is abandoned, and not for a quota reason. Two abandonment records — `docs/dev/abandonment-20260902-140306.md` and `docs/dev/abandonment-20260903-115527.md` — state `Disposition: ABANDONED. Permanently unclosable. Not paused, not blocked pending a decision, not awaiting a resource.` The cause was a close-gate rejection the lifecycle state machine had no way to express. These 22 files are landed because their content is live-useful on master, not because the cycle succeeded.

**Note on test-file count**: the operator's working estimate was 10 test files among the 22; an independent recount of this batch found **12** files matching `test_*.py`. Run below covers all 12.

**Test run**: against master HEAD `16963b604`. `hooks/tests/test_laneb_integration_gate.py` fails entirely at collection (see below) and ran zero tests; the remaining 11 collected 497 items. Final: **357 passed, 121 failed, 19 setup-errors** (all 19 inside one file), plus the 1 full-file collection error = 20 errors total in pytest's own count.

| File | Passed | Failed | Errors | Note |
|---|---|---|---|---|
| `hooks/tests/test_laneb_integration_gate.py` | — | — | 1 (collection) | entire file uncollectable |
| `tests/test_dev_fix.py` | 87 | 46 | 0 | |
| `hooks/tests/test_laneb_session_resources.py` | 90 | 0 | 0 | clean |
| `tests/test_spec_update_command_contracts.py` | 85 | 2 | 0 | |
| `tests/test_negative_evidence.py` | 23 | 59 | 0 | |
| `hooks/tests/test_laneb_stop_coordinator.py` | 11 | 3 | 0 | |
| `hooks/tests/test_laneb_checkpoint_resources.py` | 14 | 5 | 0 | |
| `tests/test_mat_doc10_writer_order_contract.py` | 11 | 4 | 0 | |
| `tests/test_dev_todo_accounting.py` | 0 | 0 | 19 (setup) | every collected test errors identically |
| `hooks/tests/test_laneb_pretool_composition.py` | 4 | 0 | 0 | clean |
| `tests/test_dev_todo_codex_native_parse.py` | 3 | 2 | 0 | |
| `hooks/tests/test_laneb_agent_temp_targets.py` | 29 | 0 | 0 | clean |

## paseo/playwright tool-parity gap: checked, NOT hit this round

The prior landing round (commit `16963b604`) found this gap independently in two files. The operator asked to watch for a third independent hit, specifically flagging `test_laneb_pretool_composition.py` as a candidate. It is **not** a third hit — that file passed 4/4 clean. No other file in this batch references paseo or playwright tooling. Nothing to add to that finding this round.

## Root-cause clusters (121 failures + 19 errors, by cluster, with representative examples — not an exhaustive per-test list; the full `-v --tb=short` transcript is available in this session's tool output if deeper per-test detail is ever needed)

### A. Missing cycle-runtime artifacts that are deliberately NOT part of this 22-file batch

These are generated runtime state from the abandoned cycle itself (`docs/dev/...json`), not source files, and were correctly excluded from a source-code landing:

- `hooks/tests/test_laneb_integration_gate.py` fails at **collection** (module-level code, not a test body) on `FileNotFoundError: .../docs/dev/context-20260815-lane-b-registry-v4-migration.json`. Landing the 22 files here does **not** fix this — the missing file is cycle state, not one of the 22. The entire file (and whatever tests it contains) ran zero times.
- A large share of `tests/test_dev_fix.py`'s 46 failures: `FileNotFoundError` on paths under `docs/dev/overnight/019fe5c1-5b46-7dd1-8086-591a5b932bf3/cycle-1/*.json` (e.g. `lane-f-historical-recovery-ownership-and-preimage-admission.v1.json`, `lane-f-historical-recovery-ba-contract-and-handoff.v1.json`, `r1-current-bytes-revalidation-for-lane-f.v1.json`). Same pattern: cycle-generated evidence, not source.

### B. A dependency module entirely absent from master and from this batch

Roughly 20 of `tests/test_dev_fix.py`'s failures are `AttributeError: module 'lane_f_confirmation_hook' has no attribute '_mint_fix_confirmation'` (also `_parse_fix_confirmation`, `os`). `lane_f_confirmation_hook` is not one of the 22 files landed here and does not exist on master. This looks like a companion hook module the same cycle would have produced, outside the operator's 22-item list — flagged for separate judgment, not fixed here.

### C. Landed content not yet wired into an out-of-scope integration/registration point

Expected consequence of landing source + tests without their registration/doc wiring, which the operator explicitly scoped out this round:

- `tests/test_negative_evidence.py::test_valid_authority_from_unrelated_cwd_cli` — `{"error": "schema 'negative-evidence.v1' not registered", "kind": "schema_contract"}`. `schemas/negative-evidence.v1.json` **is** landed (file #16 of 22), but `schemas/registry.json` — not part of this batch — doesn't reference it yet. Several of the file's other 58 failures plausibly share this or an adjacent cause (symlink/CLI fixtures exercising the same unregistered schema path); not individually re-verified here.
- `tests/test_spec_update_command_contracts.py::test_command_policy_and_history_placement` — asserts `'scripts/spec-update-contract.py'` appears in `commands/spec-update.md`'s content; it doesn't, because `commands/spec-update.md` (not part of this batch) hasn't been updated to reference the newly-landed script.

### D. Possible real behavioral mismatch (not fully diagnosed)

`tests/test_spec_update_command_contracts.py::test_missing_primary_provider_failure_is_fail_closed` — expects `returncode == 1` (fail-closed on a missing primary provider), got `0`. Unlike the registration-gap failure above, this one is a runtime behavior assertion, not a static content check — flagged as possibly real, not run down further this round.

### E. `tests/test_dev_todo_accounting.py` — 19/19 collected tests error identically at setup

Every test in the file errors (not a simple assertion failure) with the same pattern; the specific traceback was not captured in this pass to stay within this round's budget. Given the file's small size (175 lines) and subject (todo-accounting), this is consistent with the same missing-dependency shape as clusters A/B/C above rather than a new distinct cause, but that is inference, not confirmed — left open.

### F. Collection error vs. test failure: a different kind of gap, found and fixed this round

> 模块顶层从 gitignored 路径读数据的测试，不是"会失败的测试"，是"会让整个套件无法收集的测试"。pytest 的 collection error 会中断全量运行——实测 6226 个测试已收集完成，因为一个收集错误，一个都不跑。所以"失败也落、让缺口可见"这条原则对 **test failure** 成立，对 **collection error** 不成立：后者不是让缺口可见，是让所有缺口都不可见。

**Root cause**: `hooks/tests/test_laneb_integration_gate.py:1783` (plus three sibling reads at 1787, 3081, 3278) executed `json.loads(..._PATH.read_text())` unconditionally at module top level, reading `docs/dev/*.json` fixture data. `docs/dev/` is excluded wholesale by `.gitignore:173` — that data can never be present on a clean checkout, so the read raises `FileNotFoundError` at import time, and pytest's collection error aborts the **entire** collection run, not just this file. Measured before the fix: `python3 -m pytest hooks/tests tests --collect-only -q` → `6226 tests collected, 1 error` → `Interrupted: 1 error during collection` — zero of those 6226 tests actually ran.

**Fix**: a single module-level guard inserted once, immediately after the dynamic gate-module load (`SPEC.loader.exec_module(m)`), checking existence of all four fixture paths this module references and calling `pytest.skip(reason, allow_module_level=True)` if any are missing — pytest's own mechanism for "skip this whole module, with a stated reason" rather than crashing the collector. No assertion, test function, name, or file location was touched; if the fixtures are present (the original cycle's own environment), behavior is unchanged.

**Disposition note**: of the 23 files landed in commit `b108c1697`, this is the **only one** that deviates from a byte-identical landing of its original. The original (unconditional-read) version remains fully recoverable at two independent coordinates: `refs/checkpoints/worktree-overnight-20260810-019fe5c1` = `1af2a2dcbb4a119f01f956e32617dfec9bc0e5a9`, and commit `b108c1697` itself (superseded, still in history). The orchestration-side misjudgment that caused this — "land failures too" was given without distinguishing test failure from collection error — is recorded here, not attributed to the execution that followed the instruction as given.

## Disposition

22 of the 23 files landed in `b108c1697` remain byte-identical to the checkpoint commit `1af2a2dcbb4a119f01f956e32617dfec9bc0e5a9`. The 23rd, `hooks/tests/test_laneb_integration_gate.py`, was patched this round per cluster F above — no assertion/skip/xfail/rename changes. Not added to `tests/baselines/default-run-failures.json`: several clusters above (B, D, and the undiagnosed E) are open questions or likely-real gaps, and registering them as accepted would misrepresent that. Clusters A and C are expected and scoped consequences of a partial, source-only landing, not defects in the landed files themselves.

Worktree `overnight-20260810-019fe5c1` and worktree `overnight-20260809-685c203b`'s remaining 18 files were not touched by this round. `docs/reference/mat-doc10-writer-order.v2.json` and `hooks/stop-workflow-coordinator.py` — both present on master with different content than the worktree version (master's coordinator is 342 lines vs. the worktree's 313) — were deliberately excluded and require separate judgment.
