## Review follow-up

The review of this PR (head `287269e`) produced twelve findings. Eight commits on top of it act on them. Nothing was rewritten or force-pushed, and every commit ends with the two required trailer lines (`Co-Authored-By`, `Claude-Session`). Base measured against: unchanged, origin/master `f8c18c2`.

| Commit | Subject |
|---|---|
| `1a3201e` | P1: G2's legacy report check judges only the stopping producer's own report |
| `1c6f677` | P1: the remaining owner questions in agent prose go through the artifact |
| `2058242` | P1: qa.md names completed as the only dev.status |
| `d47887e` | P1: dispatched_at placeholders ask for UTC ending in Z |
| `5c92957` | P1: progress_measure names its one remaining consumer |
| `b9699dc` | P1: command_span ships only the span G1 reads |
| `7ef1835` | P1: every UserPromptSubmit ends the turn state, typed or not, pinned by a test |
| `3a18cb1` | P1: do-block test fixtures go where the hook reads them |

### Findings
- **F1** (high). Landing on an in-flight fan-out cycle wedged a compliant sibling lane. **Fixed in `1a3201e`.** G2's legacy report-schema check now judges only the stopping producer's own report. That report is identified by the task_id its dispatch obligation names, and the name is read even when the obligation no longer parses. New regression test (fails on `287269e`, passes now) and a fan-out case added to acceptance 18 (below).
- **COV-1** (medium). Some owner questions still left through a status or a STOP-and-ask instead of the artifact. **Fixed in `1c6f677`.** Each now goes through `docs/dev/producer-question-<task>-<role>.json`, as row 20 did:
  - dev's destructive-history consent (No Band-Aid item 7);
  - the Minimum-Diff STOP-and-ask (the 20-line budget and the quality-gate block);
  - BA's cross-role checkpoint escalation;
  - BA's `localization_blocked` STOP, with the matching check in commands/dev.md.
- **COV-2** (medium). **Dismissed.** The `Co-Authored-By` trailer is the attribution line the platform requires on every commit. It is not a model identifier in the PR's content, so it stays (reviewer decision, D18).
- **COV-3** (low). **Fixed in `2058242`.** agents/qa.md lists `dev.status` as `completed` only. A dev question arrives as the question artifact.
- **COV-4** (low). **Fixed in `5c92957`** (consumer docstring). The two functions left with no production caller are **noted for P10** under "Out of scope, found".
- **COV-5** (low). **Fixed in `b9699dc`.** command_span ships only what P1 consumes. The span keeps its command, args and start line, and the tool-use accessors are gone. Proof by grep below.
- **COV-6** (low). The six rows the review found without an experiment now carry a backing test, a run or a mutation and its result, or say why no alternative was tested ("Technical choices, follow-up").
- **COV-7** (low). The capture text is corrected to the measured scheduled-prompt record ("Capability capture, corrected").
- **A13-5** (low). **Fixed in `d47887e`.** All 12 `dispatched_at` placeholders ask for ISO-8601 UTC ending in Z, for example the output of `date -u +%Y-%m-%dT%H:%M:%SZ`. No check added.
- **F2** (low). The behaviour stays as row 25 says. **Docstring and test in `7ef1835`.** The reading is recorded below.
- **T3** (low). **Fixed in `3a18cb1`.** test_do_block_subagents.py's fixtures go to the hook state dir, so test_i holds with HOME, CLAUDE_CONFIG_DIR and CLAUDE_STATE_DIR in tmp_path.
- **T4** (low). **Noted for P3** under "Out of scope, found". No code change.

### Changes (follow-up)

**F1 (G2 legacy path)**
- `hooks/subagentstop-artifact-contract-enforce.py:252` `_dispatch_task_id(prompt)`: the task_id the dispatch's own `<obligation v="1">` block names. It is read from the raw block body, so it is found even when the block fails P1's grammar.
- `:267` `_own_reports(paths, prefix, task_id)`: of the session-correlated reports, those named `<prefix><task_id>.json` or declaring that task_id (minted or canonical form).
- `:862` `resolution = None`, `:1226` the legacy path narrows the correlated reports to the producer's own when its dispatch names a task_id.
- The module docstring (`:52-55`) and `_find_correlated_reports`'s docstring say this.
- `hooks/lib/obligation.py:266`: `Unresolvable.prompt` (default `""`). `:785` and `:788` fill it for `invalid_obligation` and `role_mismatch`, the two outcomes where the dispatch prompt was read and correlated. The advisory record does not log it.
- `hooks/tests/test_artifact_contract_enforce.py:2560-2630`: `test_fanout_legacy_check_judges_only_the_stopping_lanes_own_report[l2_valid|l2_invalid × switch_unset|stopgate_block]`.
- `:785` test_ac6's fall-through report declares the agent's own task_id (it is still named by the session timestamp), so the legacy path the test falls through to still judges a report of that producer. Its assertions are unchanged.

**COV-1, COV-3 (prose)**
- `agents/dev.md:903` item 7: dev never runs the destructive command. It writes its question artifact (the command in `need`, a forward-fix alternative among the options) instead of returning `destructive_action_requires_user_consent`.
- `agents/dev.md:23`: the contract-violation paragraph says that a conflict needing the owner's consent is asked through the artifact.
- `agents/dev.md:853`: above the 20-line budget, dev asks with the question artifact before the first edit. The options are the budget-sized change and the larger one.
- `agents/dev.md:863-865`: a quality-gate block that needs unrelated code becomes an owner question, with the block-list in `why`.
- `agents/dev.md:662`: the `scope_review_requested` report field stays, because the layer and guard rules and `subagent-stop-diff-check.sh` read it. It is set by an approved larger change.
- `agents/ba.md:27` and `:414-423` (Localization blocked): how to proceed is asked with the artifact. The context records `localization_blocked` only after the owner's answer to proceed.
- `agents/ba.md:1378`: the cross-role checkpoint escalation goes through the artifact instead of `status: cross_role_waive_attempt_blocked`. The user stays the only authority over another role's cp-state.
- `commands/dev.md:365` and `:386`: the location check accepts the `localization_blocked` context record instead of a BA status.
- `agents/qa.md:249`: `dev.status` is `completed` only.

**A13-5**: `commands/dev.md:450`, `commands/dev-command.md:340`, `commands/dev-overnight.md:996`, `commands/close.md:553-555`, `:559-561`, `:606`, and `commands/commit.md:509`, `:617`.

**COV-4**: `hooks/lib/progress_measure.py:4-12` names one consumer, the L2 SubagentStop producer gate (finding_id, world_fingerprint, record_round, clear_state).

**COV-5**: `hooks/lib/command_span.py` (new file, now 57 lines) keeps `Span(command, args, start_line)` and `active_span()`. `Span.calls`, `last_todos`, `final_text`, `ToolUse` and the tool-use collection loop are deleted. In hooks/tests/test_command_span.py the three accessor tests and the `span.uses` assertions in two opener tests are deleted. Every opener assertion stays.

**F2**: `hooks/prompt-workflow.py:2000-2006` docstring. `hooks/tests/test_prompt_workflow_turn_state.py:413` `test_a_prompt_the_human_did_not_type_also_ends_the_turn_state[task_notification|scheduled_prompt]`.

**T3**: `hooks/tests/test_do_block_subagents.py:38-44` loads the hook's own resolver (`hooks/lib/harness_state_dir.py`) by path. `:89` the consent flag and `:102` the /allow Agent grant are written there. The grant moves with the flag; otherwise test_f would stop testing the grant once the flag became visible.

### Release note 1, amended
Where a dispatch's obligation does not resolve (no obligation, or one minted from a pre-P1 template), the legacy report-schema check blocks that dev's SubagentStop only on **its own** report. The own report is the one named by the task_id its dispatch obligation carries. A sibling lane's `blocked` or `needs_review` report is judged at that sibling's own stop, never at another lane's. Without any obligation in the dispatch prompt, or with `CLAUDE_OBLIGATION_STOPGATE=off`, the check stays session-scoped as before.

### Reading for the reviewer (F2)
Goal 7 says "at each human prompt" and row 25 says "At every UserPromptSubmit". This PR implements row 25: every UserPromptSubmit starts a new turn, typed or not. The hooks reference says the CLI also fires UserPromptSubmit for a scheduled task, a background subagent reporting back and a peer message. Each of these ends `/do` consent and resets the tool streak, as a typed prompt does. An AskUserQuestion answered inside the turn is not a UserPromptSubmit and keeps consent.

Pinned by the new task-notification and scheduled-prompt cases. They pass on this branch and on `287269e`, and fail on origin/master, whose clearers ran at Stop.

Still UNVERIFIED (no harness host): whether the CLI fires UserPromptSubmit mid-turn for a queued peer or background hand-back. If it does, a `/do` turn that receives one loses consent at that point, and P5's `/do <task-id>` re-grants it.

### Technical choices, follow-up

**Rows the review found without an experiment (COV-6):**

| Row | Backing test or run, and its result |
|---|---|
| STUB marker `# STUB: unregistered in P1; exits 0 until P10 deletes it.` | Run on this head: `grep -n '^# STUB:' hooks/stop-completion-gate.py` gives `2:# STUB: unregistered in P1; exits 0 until P10 deletes it.`, and `printf '{}' \| python3 hooks/stop-completion-gate.py; echo $?` gives `0`. The landing replay below prints the same line 2 after the pull, and the stub at the old hook-list entry exits 0. No alternative tested: TC-37 fixes the `# STUB:` prefix that P10's doctor greps, and no check reads the rest of the line. |
| Coordinator: allowed failures recorded on the phase entry; the finalizer is skipped after a recorded failure | Backing tests: `test_non_success_phase_changes_zero_resource_bytes[block\|fail\|timeout\|invalid]` (zero resource bytes changed, `finalizer_called` False), `test_auto_commit_or_cleanup_exit_2_is_recorded_and_never_relayed`, `test_timelock_instrument_failure_outside_dev_overnight_is_recorded_and_allowed`. All pass. Mutation experiment (scratch clone): deleting the "recorded failure skips the finalizer" branch (`hooks/stop-workflow-coordinator.py:310-317`) gives **36 failed / 18 passed** in test_laneb_stop_coordinator.py, against 3 failed (the pre-existing ones) unmutated. Among the 33 new failures are `[fail]`, `[timeout]` and `[invalid]` above, so running the finalizer after a failure is rejected by the contract the tests pin. |
| Coordinator relay: `failed_phase=<name>` + last 4 KB of decoded stderr; fixed line for the fallback | Backing tests: `test_block_relays_failed_phase_and_last_4kb_of_its_stderr`, `test_timelock_instrument_failure_under_typed_dev_overnight_blocks_with_fixed_line` (no exception text, argv or driver path), `test_passing_phase_notice_is_still_relayed`. All pass. Alternative measured: origin/master's hash-only relay gave 0 stderr bytes on all 18 instrument-failure Stops (acceptance 9 sandbox table, "Before"). |
| command_span port (replaces the row; COV-5) | Kept: `active_span()`, `Span(command, args, start_line)`. Dropped: the prototype's `PAUSE_RE`/`is_pause` (S1), and `calls()`, `last_todos()`, `final_text()`, `ToolUse` and the collection loop. `obligations()` and `session_families()` were never ported. Run: `git grep -nE "\.calls\(\|\.last_todos\(\|\.final_text\(\|\bToolUse\(\|span\.uses\|\.last_text\b" -- '*.py' ':!hooks/lib/command_span.py' ':!hooks/tests/test_command_span.py'` prints nothing. The only production caller is `hooks/pretool-obligation-gate.py:96`, which reads `.command`. After the removal test_command_span.py 7 passed, test_obligation_gate.py 44 passed, and the acceptance-11 grep prints nothing. Revert: add the accessors back when P4/P5 consume them. |
| Overnight Hard Rule 5 replaced in place, no renumbering | Run: `grep -noE "Hard Rules? ?(6\|7\|8\|9\|10\|11)\b" commands/dev-overnight.md` gives 6 references by number (`:8` Rule 6, `:12` and `:116` Rule 10, `:128`, `:1344` and `:1352` Rule 9). Renumbering would have to rewrite each of them. Replacing in place changes none. |
| Prose extras (overnight BA template "Clarification round: 3" -> 0; agents/ba.md round-cap rewordings; the "Issues deferred by PM triage" statistics row) | Run: `git grep -n "Clarification round" -- commands agents`. The overnight template's first-pass value (`dev-overnight.md:1012`, 0) now equals dev.md:468 and dev-command.md:355, and agents/ba.md:82 says "0 = first pass". Acceptance 7's D2 greps print nothing, and `commands/dev-overnight.md:1685` holds the triage row. No alternative tested: keeping the old lines would restate the cap rows 19/20 delete, and would mix PM triage's planning skips into the parked-pipeline count row 19 separates. |

**Choices made in this follow-up:**

| Choice | Why | How to revert |
|---|---|---|
| G2 legacy path: the producer's own report is the correlated report named `<prefix><task_id>.json` or declaring that task_id (as given, or canonical without `dev-`/`dev-command-`). The task_id comes from the dispatch's obligation block body, parsed as JSON without the grammar. The filter narrows the existing session-correlated set and never widens it. Without a task_id (no block, a non-JSON body, a null task_id, `CLAUDE_OBLIGATION_STOPGATE=off`), the set stays session-scoped. A correlated report that neither carries the task_id in its name nor declares it is not judged at this stop. dev-report v1 and v2 require `task_id`, and /close's Artifact schema gate still validates every report in the cycle's artifact chain. | D18 decision 1: each producer is judged on its own artifact at its own SubagentStop. A pre-P1 lane obligation carries `required_values`, so it no longer parses, but its task_id is intact. Experiment: the new regression test (4 cases) fails on `287269e` and passes here, and the landing replay below goes from 3 blocks to 0. The existing union tests (`test_fanout_invalid_lane_not_shadowed_by_later_valid_sibling`, `test_fanout_invalid_canonical_not_shadowed_by_valid_shards`, `test_task_id_anchor_*`) have no obligation and still pass. | Drop the `own_task_id` narrowing (`:1226-1228`). |
| `obligation.Unresolvable` gains `prompt` (default `""`), filled only for `invalid_obligation` and `role_mismatch` | G2 needs the correlated dispatch prompt where the obligation fails. Re-resolving the transcript in G2 would duplicate the L0/L1 ladder. No caller compares Unresolvable by value (grep), and the advisory record does not log the prompt. test_obligation.py, test_e2e_enforce.py and test_artifact_contract_enforce.py give the same results as on `287269e`. | Remove the field and read the L0 `agent_transcript_path` in G2. |
| COV-1: the dev report keeps `scope_review_requested`. The context keeps `localization_blocked`, set only after the owner's answer. | Both fields have readers that are not owner questions: the layer and guard rules and `hooks/subagent-stop-diff-check.sh:39` read the first, and commands/dev.md's location check reads the second. Only the STOP-and-wait goes. dev.md:23/:43 and ba.md:11/:34/:69 (`contract_violation_refused`, `multi_issue_fanout_requested`, the mismatch outputs) are addressed to the orchestrator for routing, not to the owner, so they stay (P9 prose pass). | Revert `1c6f677`. |
| T3: the test loads `hooks/lib/harness_state_dir.py` by path under a private module name | It writes exactly where the hook reads, with no `sys.path` change and no `lib` module left in `sys.modules` (scripts/lib also exists). Run: 14 passed with HOME, CLAUDE_CONFIG_DIR and CLAUDE_STATE_DIR in a temp dir (6 failed on `287269e`), and 14 passed without CLAUDE_STATE_DIR. | Write `/tmp` again. |
| A13-5 placeholder text `<ISO-8601 UTC ending in Z, captured immediately before this ..., for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>` | No `"` and no backtick inside, so the close.md placeholders, which sit inside inline-code spans, and test_obligation_templates.py's `dispatched_at` fill still work (35 passed). The reviewer's G1 run: `...Z` rc 0, a naive timestamp rc 2. | Restore the old placeholder text. |

### Acceptance 18, fan-out case (added)
Replayed with the reviewer's `land.py` driver (read before reuse) in a sandbox of my own. The sandbox was built from origin/master `f8c18c2` with the kit's local setup, so every hook runs with master's `settings.json` hook list (`--settings /mnt/sb/settings.master.json`). The driver copies the branch tree over `/root/.claude` between the two lanes (the owner's `/pull`). Both lanes are dispatched from master's dev.md templates, so their obligations carry `required_values`. Lane l1's dev reports `needs_review` with a `status_rationale` under master's hooks, then the pull lands, then lane l2's dev writes its own `completed` report and stops.

| Branch tree landed | l1 stop (event 134, master hooks) | l2 stop after the pull | Exit 2 anywhere |
|---|---|---|---|
| `287269e` (before) | 8 hooks ok | events 146, 147, 148: `subagentstop-artifact-contract-enforce.py` exit 2, `ARTIFACT_CONTRACT_BLOCKED ... report .../dev-report-dev-<ts>-l1.json violates schema 'dev-report.v2': dev.status: 'needs_review' is not one of ['completed']` (the sibling's report, every attempt) | 3 |
| `3a18cb1` (this branch) | 8 hooks ok | event 146: all 8 SubagentStop hooks ok | **0** (148 events) |
| control, no pull (`3a18cb1` sandbox) | 8 hooks ok | event 145: all ok | 0 (147 events) |

The singular bullets, re-run on the same `3a18cb1` sandbox with the pull before dev (`step10`):
- `needsreview`: exactly one exit 2, at event 93, from the legacy check on the dev's **own** report `dev-report-<ts>.json`. After the dev rewrites the report as completed, its next stop (event 96) has all hooks ok, and the final Stop (event 127) is 4/4 ok.
- `completed`: no exit 2 and no GATE_ERROR.

The unit test covers both fan-out directions. l2's own `needs_review` report still blocks l2 and names only l2's report. l1's own stop is blocked on l1's report and names only that.

### Capability capture, corrected (COV-7)
Replace these three places in "Capability capture (TC-38)":
- **Capture table, row "Scheduled prompt (CronCreate, one-shot, 1 min ahead)"**:
  - CronCreate: tool_use `name:"CronCreate"`, `input{cron, prompt, recurring:false}`. Its tool_result carries `toolUseResult{id, humanSchedule, recurring:false, durable:false, nextFireAt}`.
  - The **fired prompt** was measured once the session went idle (CLI 2.1.303). It is an `enqueue` queue-operation, then a `type:"user"` record with string content, `isMeta:true`, `turnOrigin:"scheduled"`, `promptSource:"system"`, `queueSkipSlashCommands:true`, `queueSkipAttachments:true`, `turnPosition{promptIndex,turnIndex}`, and **no** `origin`.
  - ScheduleWakeup is not available outside `/loop` in this session.
- **"Conservative branch" paragraph, last sentence** becomes: "The fired scheduled-prompt record is measured. It carries `isMeta:true` and `turnOrigin:"scheduled"`, and either marker alone makes `stop_contract.prompt_text` (`hooks/lib/stop_contract.py:43-49`) exclude it. So a `/dev` it carries neither opens nor replaces a span (`test_command_span.py::test_dev_text_in_non_human_records_does_not_open`, variants `scheduled_prompt_is_meta_True` and `_False`)."
- **"Capability facts for P5", row "CronCreate prompt record"** becomes: "**measured in this session (2.1.303)**: an enqueue queue-operation, then a user record with `isMeta:true`, `turnOrigin:"scheduled"`, `promptSource:"system"` and no `origin`. Excluded by `is_human_prompt` (test above). Documented: UserPromptSubmit fires for a scheduled task. Unmeasured on a harness host."

Also stale in the body and replaced by the follow-up:
- "Changes": `hooks/lib/command_span.py (new, 104 lines): active_span(), Span.calls(), last_todos(), final_text(), ToolUse.ok` now reads `(new, 57 lines): active_span(), Span(command, args, start_line)`.
- The choices-table row "`command_span` port" is replaced by the COV-6 row above.
- Acceptance 1: the same 17-file command gives `13 failed, 605 passed, 1 skipped` (was 602 passed: +4 F1 cases, +2 F2 cases, -3 command_span accessor tests). The 13 failing ids are the same ones listed there.
- Acceptance 6: `test_artifact_contract_enforce.py` 73 passed (the four fan-out cases added); the 5 failures are the pre-existing ones.
- Acceptance 11: `test_command_span.py` 7 passed (the three accessor tests are gone).
- Acceptance 12: `test_prompt_workflow_turn_state.py` 18 passed; 13 fail on origin/master (was 16 and 11: the two F2 cases also fail against master's `prompt-workflow.py`).
- Acceptance 17 and "Net code lines": the totals are now the ones under "Net code lines (follow-up)"; of the two new libraries, stop_contract.py stays +99 and command_span.py is +57 (was +104).
- "Out of scope, found": the clause "remaining non-artifact exits (`localization_blocked`, `cross_role_waive_attempt_blocked`, dev's `destructive_action_requires_user_consent`, `scope_review_requested`) — P9" is done by `1c6f677`. The rest of that line (ba.md:3 frontmatter, the INDEX/README wording, ba.md:82-83's input label) stays for P9.

### Test evidence (follow-up)
python 3.12 venv, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, a clean environment (`env -i`) and a fresh scratch HOME per file. Two configurations:
- **plain**: HOME in scratch, CLAUDE_CONFIG_DIR and CLAUDE_STATE_DIR unset.
- **hermetic**: HOME, CLAUDE_CONFIG_DIR and CLAUDE_STATE_DIR all in the temp dir (P8's planned fixture).

Same commands on `287269e` (before) and `3a18cb1` (after), each tree a detached checkout of its commit. The four columns were run twice, the second time after a container restart; both runs gave the counts and ids below.

| File | before plain | before hermetic | after plain | after hermetic |
|---|---|---|---|---|
| hooks/tests/test_artifact_contract_enforce.py | 5 failed, 69 passed, 1 skipped | 5 failed, 69 passed, 1 skipped | 5 failed, **73** passed, 1 skipped | 5 failed, 73 passed, 1 skipped |
| hooks/tests/test_obligation_gate.py | 44 passed | 44 passed | 44 passed | 44 passed |
| hooks/tests/test_laneb_stop_coordinator.py | 3 failed, 51 passed | 3 failed, 51 passed | 3 failed, 51 passed | 3 failed, 51 passed |
| hooks/tests/test_stop_checkpoint_refusal.py | 9 passed | 9 passed | 9 passed | 9 passed |
| hooks/tests/test_command_span.py | 10 passed | 10 passed | **7** passed | 7 passed |
| hooks/tests/test_stop_contract.py | 11 passed | 11 passed | 11 passed | 11 passed |
| hooks/tests/test_obligation_templates.py | 35 passed | 35 passed | 35 passed | 35 passed |
| hooks/tests/test_prompt_workflow_turn_state.py | 16 passed | 16 passed | **18** passed | 18 passed |
| hooks/tests/test_do_block_subagents.py | 14 passed | **6 failed**, 8 passed | 14 passed | **14 passed** |
| tests/test_aggregate_dev_report.py | 146 passed | 146 passed | 146 passed | 146 passed |
| hooks/tests/test_obligation.py (obligation.py touched) | 1 failed, 54 passed | 1 failed, 54 passed | 1 failed, 54 passed | 1 failed, 54 passed |
| hooks/tests/test_progress_measure.py (progress_measure.py touched) | 13 passed | 13 passed | 13 passed | 13 passed |
| hooks/tests/test_e2e_enforce.py (other resolve_own_obligation caller) | 13 passed | 13 passed | 13 passed | 13 passed |
| **total** | 9 failed, 485 passed | 15 failed, 479 passed | 9 failed, 488 passed | **9 failed**, 488 passed |

Failing ids, compared per file:
- **No new failure** in either configuration.
- The hermetic run loses test_do_block_subagents' `test_a`, `test_b`, `test_i`, `test_j`, `test_k` and `test_l` (T3).
- The 9 that remain are the same ids before and after, in both configurations, and all are listed in "Acceptance 1" as also failing on origin/master:
  - `test_artifact_contract_enforce.py::{test_qa_schema_valid_allows, test_fanout_all_valid_lane_reports_allow, test_ac3_resolved_obligation_all_valid_bypasses_legacy_path, test_markdown_ac2_mixed_kinds_all_valid_bypasses_legacy_path, test_ac9_tests_land_in_existing_files_not_new_ones}`;
  - `test_laneb_stop_coordinator.py::{test_tracker_publishes_only_after_exact_canonical_completion, test_tracker_short_all_completed_payload_is_nonterminal, test_explicit_empty_environment_does_not_fall_back_to_ambient_trust}`;
  - `test_obligation.py::test_live_store_positive_control`.

New tests checked against the old code:
- `test_fanout_legacy_check_judges_only_the_stopping_lanes_own_report`: 4 failed on `287269e`'s hook, 4 passed now.
- The F2 cases: 2 passed on `287269e` (behaviour unchanged) and 2 failed on origin/master.

Prose tests (every test file that reads commands/ or agents/, plain configuration):
- The 30 pytest files outside the table above: **957 passed, 75 failed, 19 errors, 6 skipped on both `287269e` and `3a18cb1`**, the same 94 failing or erroring ids. The largest groups are `test_public_core_residue_gate.py` (32), `test_dual_runtime_lifecycle_e2e.py` (27) and `test_dev_todo_accounting.py` (19 setup errors). No id fails on one tree only.
- The prose validators `tests/scripts/validate-{checklist-completeness,claude-md-protection,optionality-language,step-numbering,todowrite-requirement}.py --project-root .`: the same exit codes on both trees (0, 1, 0, 0, 1) and byte-identical output.
- `tests/ws2_zero_literal_gate.py` was not run: it needs a rendered fresh clone, and this follow-up adds no path literal.

Other checks:
- `python3 scripts/install/render-settings check --staged`: exit 0.
- `bash scripts/verify-claims.sh`: `verify-claims: ALL CHECKS PASSED (wired_entries=81 lifecycle_events=9)`. No docs count changed: settings.json and the hook list are untouched.
- Both were re-run on `3a18cb1` with `PYTHONDONTWRITEBYTECODE=1` (clean environment, scratch HOME), with the same results. verify-claims' hero-provenance rerun still writes `hooks/lib/__pycache__/`, because `examples/guard-demo/run-hero-demo.sh:68` and `:78` start the hooks under `env -i`, which drops the variable. The directory is gitignored and in no commit, and it was removed from the clone after the run.
- `git diff --check 287269e`: clean.
- Every changed Python file compiles on 3.10.

### Rules added / retired (follow-up)
- Added: none.
- Retired: none.

F1 narrows the scope of the existing legacy report-schema check from "any correlated report of the session" to "the stopping producer's own report" whenever its dispatch names a task_id. COV-1 moves four owner questions onto the existing producer-question artifact; no gate changes.

### Net code lines (follow-up)
`git diff --numstat 287269e -- hooks scripts schemas ':!hooks/tests'`: +64 / -65. The whole PR against origin/master is now **+626 / -1041, net -415** (cap <= -250). commands/agents/policies against origin/master: +274 / -376, net -102.

### Rollback (follow-up)
Each follow-up commit reverts on its own, newest first: `git revert 3a18cb1 7ef1835 b9699dc 5c92957 d47887e 2058242 1c6f677 1a3201e`. Reverting `1a3201e` alone brings back the session-wide legacy check, and with it the fan-out landing wedge. No state file or schema is involved.

### Out of scope, found (new lines)
- **P10 (D17, dead code):** `hooks/lib/progress_measure.py` `finding_key` (`:95`) and `declare_awaiting_input` (`:283`, the `awaiting_input` pause phase S1 rejects) have had no production caller since `hooks/stop-completion-gate.py` became a stub. Only `hooks/tests/test_progress_measure.py` calls them. The docstring is corrected (`5c92957`); the code is P10's.
- **P3 (T4):** after D2, test_l2_ac7 and test_l2_ac13 no longer build their failing report from a `needs_review` dev-report. Row 1 removed the `terminal_value_violation` finding they relied on, so they use `_l2_unattributed_report` (an identity_mismatch). Their record-format assertions (`_l2_assert_record_fields`, `hooks/tests/test_artifact_contract_enforce.py:1753`) therefore no longer cover a D2 terminal violation.
  - A `needs_review` report now fails the schema. Its escalation record's finding key is `schema-invalid under obligation-supplied schema|<path>` (`hooks/lib/contract_runtime.py:907`), which does not match the file's `code|path` key format (`_FINDING_KEY_RE`, `:1623`; experiment by the reviewer: 2 failures when needs_review is restored).
  - The format predates P1. P3's resolver reads these records.
- **P9 (prose):** the orchestrator-routing statuses `contract_violation_refused`, `multi_issue_fanout_requested`, `recurring_mechanism_failure` and the "mismatch is a success output" returns (agents/dev.md:9, :23, :43; agents/ba.md:11, :20, :34, :69) still leave as statuses. They are addressed to the orchestrator, not the owner, so COV-1 left them.
