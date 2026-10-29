# tests

<!-- AUTO:index-stats -->
*Last updated: 2026-10-29T07:57:38Z*
**Total entries**: 113
**Convention**: kebab

## Tree
```
tests/
├── fixtures/
│   ├── `adversarial_corpus.json` - json config
│   ├── `overwrite_corpus.json` - JSON config: schema_version, task_id, guard, driver, documentation
│   ├── `pol_benign_strictness_exceptions.json` - JSON config: schema, criterion, task_id, iteration, _doc
│   ├── `pol_installed_program_allow_set.json` - JSON config: allowing, allowing_count, criterion, probe_shape, program_set_size
│   ├── `pol_iteration5_qa_matrix.v1.json` - JSON config: schema, schema_descriptor, provenance_key, digests, counts
│   ├── `pol_primary_laxity_ledger.json` - JSON config: schema, criterion, task_id, iteration, _doc
│   └── `protected-runtime.json` - JSON config: schema_version, protected_cmds, protected_launch_paths, protected_services, protected_hotfiles
├── `_fixtures_obligation_terminal.py` - hooks/tests/test_posttool_overnight_loop_terminal_gate.py (which pin that
├── `pol_replay_harness.py` - ZERO-EXECUTION CONTRACT (LANE-POL AC-R02-06). Every ``command`` string in the
├── `pol_sweep_generators.py` - WHY THIS FILE IS THE DELIVERABLE, NOT ITS OUTPUT (AC-R02-13). Two consecutive
├── `test_allowlist_consolidation.py` - Covers AC8 IS_SUBAGENT firewall scenarios and matching semantics invariants
├── `test_allowlist_git_global_opts.py` - Regression cover for task 20260928-133915: `/allow git commit` could never match
├── `test_artifact_contract_enforce.py` - The hook is the producer-side port of /close's Artifact schema gate
├── `test_attribution_adjudicator.py` - canonical aggregate view (Phase C; purely additive artifacts, nothing switched)
├── `test_attribution_journal.py` - break detection, verify script verdicts, torn-tail handling, seal
├── `test_baseline_snapshot_preflight.py` - agents/dev.md:535 declares that the orchestrator captures baseline_dirty_snapshot
├── `test_bash_execution_boundary.py` - These cover the properties the 436-case matrix cannot express on its own:
├── `test_bash_safety_context.py` - Tests strip_non_executable_contexts() in isolation, covering the main
├── `test_bash_safety_context_rules.py` - converted to COMMAND_CONTEXT_STRIPPED in hooks/pretool-bash-safety.sh
├── `test_bash_safety_git_clean.py` - hooks/pretool-bash-safety.sh (task dev-20260719-150041-a, lane r01-a)
├── `test_bash_write_targets_policy.py` - Execution-semantic write-target resolution at the exact sink use site.
├── `test_blackbox_integration.py` - WHAT THIS PROVES, AND WHAT IT EXPLICITLY DOES NOT
├── `test_block_branch_pr_worktree.py` - The hook forbids branch / PR / worktree CREATION on the Bash surface, with three
├── `test_bulk_commit_sentinel.py` - Covers:
├── `test_capability_gate.py` - Every test drives the real artefacts: the library, the PreToolUse gate hook as a
├── `test_checklist_record.py` - Every TodoWrite and Agent call the CLI ran is in the session transcript, so the
├── `test_checkpoint_pii_gate.sh` - Regression tests for the checkpoint PII/credential hard-exclude + push gate
├── `test_close_verdict_round_open.py` - `CLOSE_FINDINGS: <n> items` is the never-landing return of a QA judging round
├── `test_command_span.py` - The span is the records after the latest human-typed harness command outside
├── `test_commit_artifact_rw_boundary.py` - WHY THIS FILE EXISTS
├── `test_commit_event_pointer.py` - The privilege guard spends a grant by deleting it and, in the same step, writes one
├── `test_commit_hook_bypass_deny.py` - Three rules, enforced for the main agent and for subagents alike and ahead of the
├── `test_commit_journal.py` - attribution basis
├── `test_context_v1_rules.py` - schemas/context.v1.json carries them for G2 at BA's stop (P1b rows 4 and 5)
├── `test_contract_runtime_declared_vocab.py` - schema that declares them (P1b row 19 rule 7): the QA statuses the v1
├── `test_contract_runtime_version_dispatch.py` - hooks/lib/contract_runtime.py (ticket 20260929-104216-a, zero-failure design
├── `test_cp_checkin.py` - of ba-spec-20260427-194324.md (P1 view-trigger removal + P2 generation field)
├── `test_cycle_registry.py` - hooks/prompt-workflow.py mints the task id at UserPromptSubmit and arms the
├── `test_declaring_dispatch.py` - of who owes an artifact of a task, from the task's dispatch records in every
├── `test_dispatch_template.py` - A dispatch's template is the fence of its command's file that names its
├── `test_do_block_subagents.py` - During an active /do cycle the main agent could still dispatch dev-type
├── `test_do_taskid_mint.py` - Covers the root-cause fix for the do-report task-id collision (memory
├── `test_doc_sync_folder_doc.py` - doc-sync's regeneration, /clean's generate-folder-index.sh and generate-folder-readme.sh,
├── `test_doc_sync_hook_notices.py` - Backlog #83: a README that regen_readme() skips (no opening marker, or no closing marker)
├── `test_doc_sync_index_notices.py` - Backlog #85: the INDEX regeneration path and the CLAUDE.md section patcher now report what
├── `test_doc_sync_index_status.py` - Backlog #85: regen_index() returned None on every path, so nobody could tell a skipped INDEX
├── `test_doc_sync_regen_readme_status.py` - Backlog #83: regen_readme() returned None on every path, so nobody could tell a skipped
├── `test_doc_sync_regions.py` - Backlog #85: four unrelated marker predicates (README first occurrence, INDEX substring
├── `test_dual_runtime_lifecycle_e2e.py` - Real-entrypoint regressions for single-owner ordinary dev lifecycle.
├── `test_e2e_enforce.py` - obligation fallback (ticket 20261001-161041-r06, M1)
├── `test_env_configured_defaults.py` - or derived; such values come back only through the environment (normally the
├── `test_extract.py` - Unit tests for hooks/doc_sync/extract.py — covers all 4 defects + known-file cases.
├── `test_fail_closed_drift.py` - WHY THIS FILE EXISTS
├── `test_g2_spec_views.py` - subagent's stop by `spec-verify.py --strict` on the views its dispatch declares
├── `test_git_cmd_cross_consistency.py` - Verifies that GIT_CMD_RE (hooks/pretool-bash-safety.sh),
├── `test_git_prefix_enumeration.py` - THE DEFECT
├── `test_git_residual_override.py` - Background
├── `test_gitignore_preflight_close_contract.py` - The gate previously harvested any docs/dev/dev-report-*.json cited anywhere in an
├── `test_grep_backtrack_guard.py` - Freeze safe grep shapes and the catastrophic embedded-engine control.
├── `test_lane_completeness_watch.py` - fan-out's canonical aggregate (P1b E5): every lane report write runs the
├── `test_laneb_session_resources.py` - LANE-B actor scratch, receipt, and owned-process broker tests.
├── `test_laneb_stop_coordinator.py` - LANE-B non-destructive receipt writers and serialized Stop coordinator.
├── `test_laneb_stop_overnight_timelock_scoping.py` - Blast-radius-map.json (dev-20260910-111227/blast-radius-map-20260808-035658-laneb)
├── `test_merge_grant_write_check.py` - Experiment E11: the privilege guard's merge-grant check sat behind
├── `test_obligation.py` - Covers the four implementation ACs of ticket-20260929-104216-b:
├── `test_obligation_gate.py` - G1 is the first of five enforcement doors (spec-20260930-092323) that move
├── `test_obligation_templates.py` - Two template forms exist: literal ``<obligation v="1">`` blocks, and the
├── `test_overnight_gitenv_failclosed.py` - Two halves of one fail-open, scoped together because closing either alone leaves
├── `test_overnight_one_state_reader.py` - cycle contract's one writer (P1b row 13, E13)
├── `test_overnight_qa_sentinel_bind.py` - P1b E7 removed the one RW exception the boundary had under main's
├── `test_overnight_row13_consumers.py` - - The PM test plan, triage and retro reports and the specialists' reports are
├── `test_overnight_state_file_write_guard.py` - overnight-state write-protection (ticket 20261001-161041-r10, AC4/AC5/AC6)
├── `test_overnight_trace_evidence.py` - (P1b E3). Which report is inspected and which of its fields are required is
├── `test_overnight_trace_yield.py` - (P1b row 18)
├── `test_overwrite_guard.py` - Every assertion drives the REAL guard as a subprocess over a synthetic
├── `test_pol_generative_sweeps.py` - AC-R02-10 .. AC-R02-16 (revision 2). Every deny-side population here is
├── `test_posttool_overnight_loop_terminal_gate.py` - re-checks any artifact (P1b row 3: the G4 terminal-lane block is gone)
├── `test_privilege_guard_commit_file_operand.py` - The `-F` operand is taken from the shell-tokenised commit invocation and unquoted,
├── `test_prompt_workflow_turn_state.py` - hooks/prompt-workflow.py ``_clear_turn_state`` runs at every UserPromptSubmit: it removes
├── `test_push_gate_ancestor_cross_session.sh` - Regression test for hooks/push.sh's push-gate token scan (task 20260924-031253):
├── `test_push_no_upstream_guard.sh` - Regression test for hooks/push.sh R22 (line ~375): HAS_UPSTREAM must be
├── `test_push_sentinel_abort.sh` - Unit test for AC1 V5: hooks/push.sh self-aborts before any real git push
├── `test_reader_memos.py` - A hook that reads every dispatch of a long session asks for the same roster and
├── `test_regen_index_dirs_script.py` - Backlog #85: the script printed `regenerated: <INDEX>` for every directory, including the ones
├── `test_report_projection_contract.py` - Focused contract tests for deterministic Dev/QA v1 report projections.
├── `test_residual_false_positives.py` - Context (task 20260903-residual-fp). `classify_git_command()` returns a
├── `test_runcode_watchdog_aliases.py` - Direct lifecycle parity tests for both browser run-code provider names.
├── `test_runtime_guard.py` - Two layers:
├── `test_scratch_lifecycle.py` - Covers:
├── `test_span_lazy_reader.py` - what decides (P1b FX4: FX1's CS-1..3 and OB-2)
├── `test_spec_path.py` - and prompt-workflow.py's one decision of a run's spec built on it."""
├── `test_state_dir_path_rule.py` - Each test pairs a state file's writer with its reader: with CLAUDE_STATE_DIR pointing
├── `test_stop_checkpoint_noop_no_ref.py` - Drives the registered Stop hook, hooks/stop-workflow-coordinator.py with its four default
├── `test_stop_checkpoint_refusal.py` - Drives the registered Stop hook, hooks/stop-workflow-coordinator.py with its four default
├── `test_stop_contract.py` - Pins the command tuples, the human-typed prompt rule (is_human_prompt), the
├── `test_stop_do_report_gate.py` - Covers the contract from commands/do.md Step 5: a /do session may stop only
├── `test_stop_obligation_gate.py` - exit-0 stub (P1b row 3, Correction 6, D15)
├── `test_subagentstop_codex_enforce.py` - The codex ledger's one deciding read blocks a stopping subagent whose session
├── `test_todo_script_fork.py` - lib.todo_canonical.run_todo_script runs a harness todo script in a fork of the
├── `test_tool_policy_contracts.py` - LANE-POL least-privilege role-policy regression matrix.
├── `test_tool_policy_derived_permission.py` - hooks/pretool-tool-policy.py runs it before the role rows, for every caller, the main agent
├── `test_unit_anchor.py` - Imports the anchor sibling module DIRECTLY (not via the _core facade) and
├── `test_unit_config.py` - Imports the config sibling module DIRECTLY (not via the _core facade) and
├── `test_unit_constants.py` - Imports the constants sibling module DIRECTLY (not via the _core facade) and
├── `test_unit_find_cmds.py` - Imports the find_cmds sibling module DIRECTLY (not via the _core facade) and
├── `test_unit_git_cmds.py` - Imports the git_cmds sibling module DIRECTLY (not via the _core facade) and
├── `test_unit_pathmatch.py` - Imports the pathmatch sibling module DIRECTLY (not via the _core facade) and
├── `test_unit_shell_lex.py` - Imports the shell_lex sibling module DIRECTLY (not via the _core facade's
├── `test_userprompt_bulk_commit_capability.py` - These assertions (AC-FRESH-F-14) came from the tests of an unreachable script
├── `test_userprompt_doc_sync_relay.py` - Backlog #83: the UserPromptSubmit hook resyncs a directory by running
├── `test_userprompt_usage_snapshot.py` - Covers the three cache states the hook must handle (cache hit, cache expired
└── `test_write_push_gate_token.py` - changelog-analyst (under /commit) and the cleaner (under /clean) both call it after
```
<!-- /AUTO:index-stats -->

---
*Auto-generated by doc-sync hook.*