# hooks

<!-- AUTO:index-stats -->
*Last updated: 2026-11-10T08:16:38Z*
**Total entries**: 353
**Convention**: kebab

## Tree
```
hooks/
├── doc_sync/
│   ├── `config.py` - The git-tracked helpers (WS5, AC-WS5-1) let the INDEX/README generators list
│   ├── `docker.py` - Parse docker-compose.yml and generate markdown table.
│   ├── `extract.py` - Extract description from various file types.
│   ├── `folder_doc.py` - doc-sync's regeneration, /clean's scripts/generate-folder-index.sh and
│   ├── `main.py` - Main entry point for doc-sync hook.
│   ├── `notice.py` - A skipped README, INDEX or CLAUDE.md section is a deliberate outcome (regeneration is opt-in
│   ├── `patch.py` - Patch CLAUDE.md dynamic sections using AUTO markers.
│   ├── `regen_index.py` - Regenerate INDEX.md for a directory.
│   ├── `regen_readme.py` - Regenerate README.md for a directory.
│   ├── `regions.py` - Four unrelated predicates used to decide what a file's AUTO region is (README first
│   └── `tree.py` - Build directory trees for INDEX.md.
├── git-hooks/
│   ├── `post-commit-auto-push` - post-commit-auto-push file
│   └── `pre-commit` - pre-commit file
├── git-keystone/
│   └── `reference-transaction` - reference-transaction file
├── lib/
│   ├── runtime_guard/
│   │   ├── `_core.py` - This module contains ZERO project identifiers. Every project-specific name
│   │   ├── `anchor.py` - The cleanly-extractable leaf subset of the HEAD-AGNOSTIC P0 anchor scan
│   │   ├── `config.py` - Depends on shell_lex (`_strip_quotes`, `_has_redirect_to`) + pathmatch
│   │   ├── `constants.py` - Dependency LEAF: defines only literal frozenset/dict constants, imports nothing,
│   │   ├── `context.py` - `_core.evaluate` computes a small set of per-EVALUATION inputs ONCE — the
│   │   ├── `find_cmds.py` - Depends on shell_lex (`_strip_quotes`) + pathmatch (`_glob_to_segment_regex`,
│   │   ├── `git_cmds.py` - Depends on shell_lex (`_strip_quotes`) + pathmatch (`_expand_leading_home`) +
│   │   ├── `pathmatch.py` - Depends only on shell_lex (`_strip_quotes`) + stdlib; references nothing from
│   │   └── `shell_lex.py` - Dependency LEAF: imports only the stdlib, references nothing from _core
│   ├── write_gate/
│   │   └── `overwrite.py` - The Python form of hooks/pretool-write-guard.sh, decision for decision and message for
│   ├── `agent_cycle.py` - producer (posttool-codex-skill-ledger.py) and the hooks that read a cycle's
│   ├── `agent_resolver.py` - Refactored from pretool-subagent-code-block.py::_find_agent_type so that
│   ├── `allowlist.py` - The /allow grant file's one writer (write_sentinel_grant) and its readers,
│   ├── `attribution_journal.py` - Capture side (used by pretool-attribution-pre.py / posttool-attribution-post.py):
│   ├── `auto_push.sh` - auto_push.sh -- harness_auto_push, the one reader of the per-repository push switch.
│   ├── `bash_active_syntax_census.py` - WHY THIS MODULE EXISTS (spec-20260808-035658 LANE-POL, Must-2 "completeness
│   ├── `bash_context_strip.py` - This is deliberately NOT a full shell parser.  It only computes a conservative
│   ├── `bash_execution_boundary.py` - THE ALGEBRA (spec-20260808-035658 LANE-POL, Must-1).  Every execution-bearing
│   ├── `bash_write_targets.py` - Provides two public functions used by tool-policy and overnight-hook-guard:
│   ├── `capability_state.py` - verdict, and the INDEPENDENT (non-hook-dispatched) preactivation consumer
│   ├── `checkpoint-core.sh` - checkpoint-core.sh - Shared library for automated snapshot commits
│   ├── `claude_home.py` - Generalizes the in-repo gold-standard fail-closed self-resolution pattern
│   ├── `claude_home.sh` - claude_home.sh — shared "harness home" resolver (shell consumable).
│   ├── `close-verdict.py` - The one rule every reader of a close verdict applies: classify the close
│   ├── `close_rating.py` - The owner's close rating: handle() writes its row and returns the owner summary; the predicates P5's Stop gate imports.
│   ├── `closeout.py` - CLI:
│   ├── `command_span.py` - rule of which transcript record is a prompt the human typed
│   ├── `commit_journal.py` - WHY THIS EXISTS
│   ├── `commit_pipeline.py` - ONE home for the two questions the commit-authorization chain could not
│   ├── `contract_runtime.py` - This module is the single shared engine consumed by every contract-aware
│   ├── `declared_paths.py` - hooks/pretool-tool-policy.py decides who may write a path a dispatch of the
│   ├── `dev_loop_checks.py` - Five hooks held these checks (pretool-layer-escalation-check.sh, pretool-bisect-gate.sh,
│   ├── `dev_report_shard_patterns.py` - Single source for the per-worker / canonical dev-report filename regexes and
│   ├── `dispatch_template.py` - A dispatch made from a base template before a merge carries no obligation block
│   ├── `do_report.py` - `docs/dev/do-report-<task_id>.json` has one producer, the /do main agent. Every
│   ├── `gate_runner.py` - Claude Code starts every hook registered on an event at once, so two hooks that
│   ├── `git_clean_guard.py` - Classifies ONE Bash command for the fail-closed pre-clean guard woven into the
│   ├── `git_command_classifier.py` - Provides iter_git_invocations() — a token-aware parser that detects git
│   ├── `grepguard_context_strip.py` - PURPOSE (narrow, guard-specific)
│   ├── `harness_state_dir.py` - Hook runtime state (consent flags, grants, sentinels, bookmarks, stamps) lives
│   ├── `harness_state_dir.sh` - harness_state_dir.sh -- shell twin of hooks/lib/harness_state_dir.py.
│   ├── `interruption_signals.py` - Decides whether a subagent was cut off — and whether a usage limit did it — from
│   ├── `merge_grant.py` - The merge-analyst writes its grant with the Write tool at
│   ├── `obligation.py` - Rollout step S2 of the converged zero-failure design
│   ├── `overnight.py` - The state record `<main root>/.claude/overnight-state-<sid>.json` has one producer,
│   ├── `pol_degraded_removal_reference.ere` - ere file
│   ├── `policy_registry.py` - Reads the harness ``policies/tool-policy.v1.json`` (resolved via the shared
│   ├── `roster.py` - A role exists because ``agents/<role>.md`` exists and opens with YAML front
│   ├── `rule_runner.py` - A merged gate (hooks/pretool-write-gate.py) holds several rules that were
│   ├── `runtime_guard.py` - This file exists for backwards-compatibility with callers that invoke
│   ├── `schema_registry.py` - Reads schemas/registry.json once and lazily loads referenced schema files
│   ├── `score_events.py` - Score events from facts: sweep() appends the active span's events to the score log; observe() is the dispatch hook's entry.
│   ├── `score_log.py` - and views are computed on read, never stored. Rows: event {kind, ts, project, task_id, role, even...
│   ├── `scratch_owner.py` - hooks/session-scratch-init.sh writes <root>/<sid>/.owner = {"sid": ..., ...}. One rule reads
│   ├── `session_resources.py` - Every destructive operation is bound to an immutable resource session and a
│   ├── `spec_path.py` - One rule, two callers: prompt-workflow.py decides a /dev, /dev-command, /redev or
│   ├── `specialist_yield.py` - Public API:
│   ├── `stop-commands.json` - JSON config: GATED_COMMANDS, CONTROL_COMMANDS
│   ├── `stop_contract.py` - is a prompt the human typed (TC-4)
│   ├── `subagent.py` - is_subagent_context() and supporting helpers, for the hooks that import it
│   ├── `subagent_restart.py` - Claude Code persists each subagent transcript under the parent session.  This
│   └── `todo_canonical.py` - Shared canonical todo validation utilities
├── tests/
│   ├── fixtures/
│   │   ├── `adversarial_corpus.json` - json config
│   │   ├── `pol_benign_strictness_exceptions.json` - JSON config: schema, criterion, task_id, iteration, _doc
│   │   ├── `pol_installed_program_allow_set.json` - JSON config: allowing, allowing_count, criterion, probe_shape, program_set_size
│   │   ├── `pol_iteration5_qa_matrix.v1.json` - JSON config: schema, schema_descriptor, provenance_key, digests, counts
│   │   ├── `pol_primary_laxity_ledger.json` - JSON config: schema, criterion, task_id, iteration, _doc
│   │   └── `protected-runtime.json` - JSON config: schema_version, protected_cmds, protected_launch_paths, protected_services, protected_hotfiles
│   ├── `_fixtures_obligation_terminal.py` - hooks/tests/test_posttool_overnight_loop_terminal_gate.py (which pin that
│   ├── `pol_replay_harness.py` - ZERO-EXECUTION CONTRACT (LANE-POL AC-R02-06). Every ``command`` string in the
│   ├── `pol_sweep_generators.py` - WHY THIS FILE IS THE DELIVERABLE, NOT ITS OUTPUT (AC-R02-13). Two consecutive
│   ├── `retired_hooks.py` - A test that compares a merged rule with the hook it replaced (the write gate's overwrite rule with
│   ├── `test_aggregate_check_obligation_scope.py` - from the QA dispatch's own obligation (P3 row 12)
│   ├── `test_allowlist_consolidation.py` - Covers AC8 IS_SUBAGENT firewall scenarios and matching semantics invariants
│   ├── `test_allowlist_git_global_opts.py` - Regression cover for task 20260928-133915: `/allow git commit` could never match
│   ├── `test_artifact_contract_enforce.py` - G2 checks the artifacts a subagent's own dispatch obligation declares at its
│   ├── `test_attribution_journal.py` - break detection, verify script verdicts, torn-tail handling, seal
│   ├── `test_ba_qa_routing_record.py` - A BA or QA handed several issues stops before any analysis and replies `multi_issue_fanout_reques...
│   ├── `test_bash_execution_boundary.py` - These cover the properties the 436-case matrix cannot express on its own:
│   ├── `test_bash_safety_channel_script_operand.py` - script operand spelled through the quoted CLAUDE_HOME channel as the named script file it is,
│   ├── `test_bash_safety_context.py` - Tests strip_non_executable_contexts() in isolation, covering the main
│   ├── `test_bash_safety_context_rules.py` - converted to COMMAND_CONTEXT_STRIPPED in hooks/pretool-bash-safety.sh
│   ├── `test_bash_safety_git_clean.py` - hooks/pretool-bash-safety.sh (task dev-20260719-150041-a, lane r01-a)
│   ├── `test_bash_views_guard.py` - the quoted CLAUDE_HOME channel spelling P2 R6 gave every command line, as it
│   ├── `test_bash_write_targets_policy.py` - Execution-semantic write-target resolution at the exact sink use site.
│   ├── `test_blackbox_integration.py` - WHAT THIS PROVES, AND WHAT IT EXPLICITLY DOES NOT
│   ├── `test_block_branch_pr_worktree.py` - The hook forbids branch / PR / worktree CREATION on the Bash surface, with three
│   ├── `test_bulk_commit_sentinel.py` - Covers:
│   ├── `test_c_layer_protected_targets.py` - d1b244f0 made a shell `-c` layer fail closed: run-time text given to a program outside
│   ├── `test_capability_gate.py` - Every test drives the real artefacts: the library, the PreToolUse gate hook as a
│   ├── `test_checklist_record.py` - Every TodoWrite and Agent call the CLI ran is in the session transcript, so the
│   ├── `test_checkpoint_pii_gate.sh` - Regression tests for the checkpoint PII/credential hard-exclude + push gate
│   ├── `test_claude_config_guard.py` - /dev-command develops project slash commands, so its dev writes the command file the cycle asks
│   ├── `test_cli_role_own_cycle.py` - their cycle from the agent's own dispatch obligation
│   ├── `test_close_rating.py` - hooks/posttool-close-rating.py, the rating row's one writer and the owner summary it prints (thro...
│   ├── `test_close_verdict_round_open.py` - `CLOSE_FINDINGS: <n> items` is the never-landing return of a QA judging round
│   ├── `test_command_span.py` - The span is the records after the latest human-typed harness command outside
│   ├── `test_commit_artifact_rw_boundary.py` - WHY THIS FILE EXISTS
│   ├── `test_commit_event_pointer.py` - The privilege guard spends a grant by deleting it and, in the same step, writes one
│   ├── `test_commit_hook_bypass_deny.py` - Three rules, enforced for the main agent and for subagents alike and ahead of the
│   ├── `test_commit_journal.py` - attribution basis
│   ├── `test_context_v1_rules.py` - schemas/context.v1.json carries them for G2 at BA's stop (P1b rows 4 and 5)
│   ├── `test_contract_runtime_declared_vocab.py` - schema that declares them (P1b row 19 rule 7): the QA statuses the v1
│   ├── `test_contract_runtime_version_dispatch.py` - hooks/lib/contract_runtime.py (ticket 20260929-104216-a, zero-failure design
│   ├── `test_cp_checkin.py` - of ba-spec-20260427-194324.md (P1 view-trigger removal + P2 generation field)
│   ├── `test_cp_enforce_own_slot.py` - cp-state slot's pending checkpoints (P1c X6)
│   ├── `test_cycle_registry.py` - hooks/prompt-workflow.py mints the task id at UserPromptSubmit and arms the
│   ├── `test_declaring_dispatch.py` - of who owes an artifact of a task, from the task's dispatch records in every
│   ├── `test_dev_loop_checks.py` - - Before a dev dispatch (PreToolUse): layer escalation and bisect; after it returns (PostToolUse):
│   ├── `test_dispatch_template.py` - A dispatch's template is the fence of its command's file that names its
│   ├── `test_do_block_subagents.py` - During an active /do cycle the main agent could still dispatch dev-type
│   ├── `test_do_consent_landing.py` - hooks/prompt-workflow.py, the flag's one writer, writes it on a `/do ...` UserPromptSubmit into
│   ├── `test_do_taskid_mint.py` - Covers the root-cause fix for the do-report task-id collision (memory
│   ├── `test_doc_sync_folder_doc.py` - doc-sync's regeneration, /clean's generate-folder-index.sh and generate-folder-readme.sh,
│   ├── `test_doc_sync_hook_notices.py` - Backlog #83: a README that regen_readme() skips (no opening marker, or no closing marker)
│   ├── `test_doc_sync_index_notices.py` - Backlog #85: the INDEX regeneration path and the CLAUDE.md section patcher now report what
│   ├── `test_doc_sync_index_status.py` - Backlog #85: regen_index() returned None on every path, so nobody could tell a skipped INDEX
│   ├── `test_doc_sync_regen_readme_status.py` - Backlog #83: regen_readme() returned None on every path, so nobody could tell a skipped
│   ├── `test_doc_sync_regions.py` - Backlog #85: four unrelated marker predicates (README first occurrence, INDEX substring
│   ├── `test_doc_sync_update_only.py` - A Write in a product repository leaves no CLAUDE.md, INDEX.md or README.md behind that was
│   ├── `test_dual_runtime_lifecycle_e2e.py` - Real-entrypoint regressions for single-owner ordinary dev lifecycle.
│   ├── `test_e2e_enforce.py` - is judged on
│   ├── `test_env_configured_defaults.py` - or derived; such values come back only through the environment (normally the
│   ├── `test_extract.py` - Unit tests for hooks/doc_sync/extract.py — covers all 4 defects + known-file cases.
│   ├── `test_fail_closed_drift.py` - WHY THIS FILE EXISTS
│   ├── `test_g2_file_lists.py` - files Claude Code recorded the dev writing (hooks/subagentstop-artifact-
│   ├── `test_g2_harness_syntax.py` - artifact-contract-enforce.py, _harness_syntax) parses every file of the
│   ├── `test_g2_spec_views.py` - subagent's stop by `spec-verify.py --strict` on the views its dispatch declares
│   ├── `test_git_cmd_cross_consistency.py` - Verifies that GIT_CMD_RE (hooks/pretool-bash-safety.sh),
│   ├── `test_git_prefix_enumeration.py` - THE DEFECT
│   ├── `test_git_residual_override.py` - Background
│   ├── `test_git_shell_c_strings.py` - `bash -c "git commit -m y"` runs git, but the shell segment's command token is
│   ├── `test_gitignore_preflight_close_contract.py` - The gate previously harvested any docs/dev/dev-report-*.json cited anywhere in an
│   ├── `test_grant_binding.py` - hooks/pretool-tool-policy.py, beside the derived write permission and for every caller alike:
│   ├── `test_grep_backtrack_guard.py` - Freeze safe grep shapes and the catastrophic embedded-engine control.
│   ├── `test_hook_output_reaches_model.py` - The CLI (code.claude.com/docs/en/hooks): plain stdout reaches the model on SessionStart and
│   ├── `test_inflight_push_route.py` - COMPATIBILITY TESTS, kept only as long as hooks/pretool-tool-policy.py's _note_inflight_token_rou...
│   ├── `test_lane_completeness_watch.py` - fan-out's canonical aggregate (P1b E5): every lane report write runs the
│   ├── `test_laneb_session_resources.py` - LANE-B actor scratch, receipt, and owned-process broker tests.
│   ├── `test_laneb_stop_coordinator.py` - LANE-B non-destructive receipt writers and serialized Stop coordinator.
│   ├── `test_laneb_stop_overnight_timelock_scoping.py` - Its time-lock and wake check are the Stop gate's step 4 (hooks/stop-command-gate.py,
│   ├── `test_merge_grant_write_check.py` - Experiment E11: the privilege guard's merge-grant check sat behind
│   ├── `test_notification_idle_overnight.py` - (P12), and the file stays for a session that loaded an older hook list (D15)."""
│   ├── `test_obligation.py` - Covers the four implementation ACs of ticket-20260929-104216-b:
│   ├── `test_obligation_gate.py` - G1 is the first of five enforcement doors (spec-20260930-092323) that move
│   ├── `test_obligation_templates.py` - Two template forms exist: literal ``<obligation v="1">`` blocks, and the
│   ├── `test_one_process_gates.py` - - The runner keeps each rule's decision: a rule runs as its own hook would run alone,
│   ├── `test_overnight_cycle_contract.py` - - No seed file: the exploration (steps 2-4) passes the dispatch hook in cycles
│   ├── `test_overnight_git_config_write_guard.py` - The keystone's core.hooksPath lives in the repository's git config. bubblewrap's
│   ├── `test_overnight_gitenv_failclosed.py` - Two halves of one fail-open, scoped together because closing either alone leaves
│   ├── `test_overnight_inplace_bubblewrap.py` - Replayed in a bwrap-less in-place toy session, every removal of the git
│   ├── `test_overnight_one_state_reader.py` - cycle contract's one writer (P1b row 13, E13)
│   ├── `test_overnight_operand_scan_channel.py` - The commands run harness scripts as `bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/x.sh"`. For an
│   ├── `test_overnight_qa_sentinel_bind.py` - P1b E7 removed the one RW exception the boundary had under main's
│   ├── `test_overnight_question_deny.py` - hooks/pretool-overnight-hook-guard.py denies AskUserQuestion to every caller of
│   ├── `test_overnight_row13_consumers.py` - - The PM test plan, triage and retro reports and the specialists' reports are
│   ├── `test_overnight_state_file_write_guard.py` - overnight-state write-protection (ticket 20261001-161041-r10, AC4/AC5/AC6)
│   ├── `test_overnight_trace_evidence.py` - (P1b E3). Which report is inspected and which of its fields are required is
│   ├── `test_overnight_trace_yield.py` - (P1b row 18)
│   ├── `test_overnight_wake.py` - The wake is one recurring CronCreate of lib/overnight.py's WAKE_PROMPT, scheduled at Step 0 and d...
│   ├── `test_overnight_window.py` - window_open, closeout_gaps, stop_contract.timelock_released and the /stop helper
│   ├── `test_overwrite_guard.py` - The overwrite guard was never registered and was deleted with its route
│   ├── `test_pol_generative_sweeps.py` - AC-R02-10 .. AC-R02-16 (revision 2). Every deny-side population here is
│   ├── `test_posttool_checkpoint_refusal.py` - Drives hooks/posttool-git-checkpoint.sh as settings.json registers it (PostToolUse on
│   ├── `test_posttool_overnight_loop_terminal_gate.py` - re-checks any artifact (P1b row 3: the G4 terminal-lane block is gone)
│   ├── `test_pretool_push_analyst_grant_guard.py` - registers it (P12), and the file stays for a session that loaded an older hook list (D15);
│   ├── `test_privilege_guard_commit_file_operand.py` - The `-F` operand is taken from the shell-tokenised commit invocation and unquoted,
│   ├── `test_privilege_guard_fails_closed.py` - P9 renamed the classifier's git value-option set to GIT_GLOBAL_VALUE_OPTS; another
│   ├── `test_prompt_workflow_replay_window.py` - envelope only while its replay record is younger than 60 s, judged by the
│   ├── `test_prompt_workflow_turn_state.py` - hooks/prompt-workflow.py ``_clear_turn_state`` runs at every UserPromptSubmit: it removes
│   ├── `test_push_gate_ancestor_cross_session.sh` - Regression test for hooks/push.sh's push-gate token scan (task 20260924-031253):
│   ├── `test_push_no_upstream_guard.sh` - Regression test for hooks/push.sh R22 (line ~375): HAS_UPSTREAM must be
│   ├── `test_push_sentinel_abort.sh` - Unit test for AC1 V5: hooks/push.sh self-aborts before any real git push
│   ├── `test_push_typed_remote.py` - execute-push.py hands push.sh the resolved remote as its argument. The ahead count is taken against
│   ├── `test_reader_memos.py` - A hook that reads every dispatch of a long session asks for the same roster and
│   ├── `test_report_projection_contract.py` - Focused contract tests for the deterministic QA v1 report projection and the report gate.
│   ├── `test_residual_false_positives.py` - Context (task 20260903-residual-fp). `classify_git_command()` returns a
│   ├── `test_role_from_cli.py` - The role is the payload's agent_type when it carries an agent_id, else the agentType of
│   ├── `test_runcode_watchdog_aliases.py` - Direct lifecycle parity tests for both browser run-code provider names.
│   ├── `test_runtime_guard.py` - Two layers:
│   ├── `test_scratch_lifecycle.py` - Covers:
│   ├── `test_session_gitignore_propagate.py` - product repo are listed in the clone's own exclude file, one line each, and nothing else is writt...
│   ├── `test_skill_deny_coverage.py` - `disable-model-invocation: true` blocks the SlashCommand route only; the `Skill(<stem>:*)` entry in
│   ├── `test_span_lazy_reader.py` - what decides (P1b FX4: FX1's CS-1..3 and OB-2)
│   ├── `test_spec_path.py` - and prompt-workflow.py's one decision of a run's spec built on it, replayed at
│   ├── `test_state_dir_path_rule.py` - Each test pairs a state file's writer with its reader: with CLAUDE_STATE_DIR pointing
│   ├── `test_stop_checkpoint_noop_no_ref.py` - Drives the registered Stop hook, hooks/stop-launch.py, and the coordinator with its four default
│   ├── `test_stop_checkpoint_refusal.py` - Drives the registered Stop hook, hooks/stop-launch.py, and the coordinator with its four default
│   ├── `test_stop_command_gate.py` - The gate calls P3's disposition, P2's overnight locator and window, and P4's
│   ├── `test_stop_contract.py` - Pins the command tuples, the human-typed prompt rule (is_human_prompt), the
│   ├── `test_stop_do_report_gate.py` - The /do span is the Stop gate's (hooks/stop-command-gate.py, test_stop_command_gate.py's
│   ├── `test_stop_launch.py` - The launcher runs the Stop coordinator and relays it; when the coordinator cannot decide it
│   ├── `test_stop_md_userintent_wrapper.py` - commands/stop.md runs the release wrapper through the printed harness root. hooks/pretool-wrapper-
│   ├── `test_stop_obligation_gate.py` - stub (P1b row 3, D15) that settings.json no longer registers (P5 R12)
│   ├── `test_subagentstop_codex_enforce.py` - The codex ledger's one deciding read blocks a stopping subagent whose session
│   ├── `test_subagentstop_cp_enforce.py` - Armed as shipped (settings.json's env sets CP_ENFORCE_MODE=block), the hook blocks
│   ├── `test_test_writer_manifest_skeleton.py` - (agents/test-writer.md, agents/dev.md "Generated tests"). schemas/test-writer-manifest.v1.json
│   ├── `test_todo_script_fork.py` - lib.todo_canonical.run_todo_script runs a harness todo script in a fork of the
│   ├── `test_todo_validate_after_restart.py` - A dev subagent cut before its Agent call came back (no tool_result, or the CLI's error result aft...
│   ├── `test_todo_validate_in_flight.py` - The owner cannot stop his sessions: one that took up origin/master's /close before train 2 landed
│   ├── `test_tool_policy_contracts.py` - LANE-POL least-privilege role-policy regression matrix.
│   ├── `test_tool_policy_derived_permission.py` - hooks/pretool-tool-policy.py runs it before the role rows, for every caller, the main agent
│   ├── `test_tool_policy_protected_paths.py` - hooks/pretool-tool-policy.py refuses, before every other rule and for the main agent and every
│   ├── `test_unit_anchor.py` - Imports the anchor sibling module DIRECTLY (not via the _core facade) and
│   ├── `test_unit_config.py` - Imports the config sibling module DIRECTLY (not via the _core facade) and
│   ├── `test_unit_constants.py` - Imports the constants sibling module DIRECTLY (not via the _core facade) and
│   ├── `test_unit_find_cmds.py` - Imports the find_cmds sibling module DIRECTLY (not via the _core facade) and
│   ├── `test_unit_git_cmds.py` - Imports the git_cmds sibling module DIRECTLY (not via the _core facade) and
│   ├── `test_unit_pathmatch.py` - Imports the pathmatch sibling module DIRECTLY (not via the _core facade) and
│   ├── `test_unit_shell_lex.py` - Imports the shell_lex sibling module DIRECTLY (not via the _core facade's
│   ├── `test_userprompt_bulk_commit_capability.py` - These assertions (AC-FRESH-F-14) came from the tests of an unreachable script
│   ├── `test_userprompt_doc_sync_relay.py` - Backlog #83: the UserPromptSubmit hook resyncs a directory by running
│   ├── `test_userprompt_usage_snapshot.py` - Covers the three cache states the hook must handle (cache hit, cache expired
│   ├── `test_workflow_bookmark_writer.py` - <project>/.claude/workflow-<sid>.json is written by prompt-workflow.py alone (a
│   ├── `test_worktree_guard.py` - agent worktrees
│   ├── `test_write_gate.py` - - The gate sees what the guards saw: each rule's tool set is its guard's registered matcher
│   ├── `test_write_gate_overwrite_parity.py` - The write gate runs the Python form. The shell hook is an exit-0 stub since the gate's registration
│   ├── `test_write_guard_consent_process.py` - The file is an exit-0 stub since the write gate's registration landed (D15); its checks are the g...
│   ├── `test_write_push_gate_token.py` - changelog-analyst (under /commit) and the cleaner (under /clean) both call it after
│   └── `write_gate_settings.py` - At the P12 base (retired_hooks.BASE) settings.json registers 78 hooks of 77 files; the tracked file
├── `auto-commit.sh` - auto-commit.sh - Stop hook: snapshot on conversation end
├── `capability-canary.py` - Registered once per relied-upon lifecycle event, each registration carrying its
├── `check-todo-md-sync.py` - check-todo-md-sync.py — Session-start drift detector for todo scripts
├── `checkpoint.sh` - checkpoint.sh - Manual /checkpoint command
├── `fswatch-manager.sh` - fswatch-manager.sh - Manage git-fswatch instances
├── `git-fswatch.sh` - git-fswatch.sh - Comprehensive Git file watcher using fswatch
├── `git-fswatch@.service` - service file
├── `install-auto-sync.sh` - LEGACY / DO NOT USE — describes an obsolete auto-sync model.
├── `install-git-hooks.sh` - LEGACY / DO NOT USE — describes an obsolete git-tracking model.
├── `install-protection-all.sh` - LEGACY / DO NOT USE — describes an obsolete auto-push protection model.
├── `install.sh` - LEGACY / DO NOT USE — describes an obsolete auto-commit model.
├── `merge.sh` - merge.sh - wrapper for /merge slash command
├── `notification-idle-overnight.py` - Its only effect was appending a record to the harness home's
├── `posttool-allowlist-consume.py` - PostToolUse Hook: /allow grant consumption
├── `posttool-attribution-post.py` - Pairs with pretool-attribution-pre.py via (session_id, tool_use_id). Purely
├── `posttool-close-rating.py` - A question goes by its source prefix to one handler, an Agent call to the observer; no logic here
├── `posttool-codex-skill-ledger.py` - Fires on every PostToolUse for the Skill tool. When tool_input.skill == "codex",
├── `posttool-command-frontmatter-validate.py` - PostToolUse Hook: Validate .claude/commands/*.md frontmatter structure
├── `posttool-dispatch-record.py` - The rules run in this order, each as its own hook would run alone
├── `posttool-doc-sync.py` - PostToolUse Hook: keep the marked INDEX.md, README.md and CLAUDE.md sections in sync
├── `posttool-git-checkpoint.sh` - posttool-git-checkpoint.sh - PostToolUse checkpoint trigger
├── `posttool-git-warn.sh` - posttool-git-warn.sh - PostToolUse (Bash): after a git commit, tell the model which files it left untracked.
├── `posttool-lane-completeness-watch.py` - producer of a fan-out's canonical aggregate dev-report (P1b E5). Every write
├── `posttool-overnight-file-check.py` - PostToolUse:Agent Hook — Contract-driven overnight file check (G3)
├── `posttool-overnight-loop.py` - PostToolUse:TodoWrite Hook: Overnight Loop Detection
├── `posttool-overnight-trace.py` - Writes one JSONL trace record per Agent invocation to:
├── `posttool-push-gate-token-verify.py` - The push gate stays, with its reconciliation path (owner's decision, 2026-09-05)
├── `posttool-restart-sendmessage.py` - PostToolUse: record successful validated restart SendMessage calls.
├── `posttool-runcode-watchdog.py` - PostToolUse Hook: Cancel timeout watchdog after browser_run_code completes
├── `posttool-subagent-track.py` - PostToolUse:Agent Hook: the cycle contract's one writer (/dev-overnight)
├── `posttool-todo-count.py` - It refused, after a TodoWrite had run, a list shorter than the command's
├── `posttool-todo-sequence.py` - It re-checked, after a TodoWrite had run, the step rules
├── `posttool-todo-tracker.py` - PostToolUse Hook: Output checklist progress after every TodoWrite call
├── `pre-commit-check.sh` - pre-commit-check.sh - Detect untracked files before commit
├── `pretool-aggregate-check.py` - existence before allowing the orchestrator to dispatch the QA subagent in
├── `pretool-attribution-pre.py` - Phase 0 of the write-time attribution journal (see hooks/lib/attribution_journal.py)
├── `pretool-bash-safety.sh` - PreToolUse Safety Hook - Warn or block before dangerous operations
├── `pretool-bash-views-guard.py` - Parallels pretool-bash-safety.sh but focuses on views/cp-state write bypass
├── `pretool-bisect-gate.sh` - STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
├── `pretool-block-background-tasks.py` - PreToolUse hook: block background execution on Agent/Task/Bash/SendMessage/Workflow
├── `pretool-block-branch-pr-worktree.py` - Policy (user directive 2026-06-04; the verbatim user directive is preserved in
├── `pretool-block-enterworktree.sh` - PreToolUse hook: Block EnterWorktree tool
├── `pretool-bulk-commit-detector.py` - PreToolUse Hook: Bulk-commit detector (advisory: exit 0 always)
├── `pretool-capability-gate.py` - Blocks (exit 2) any protected-workflow activation route unless the host-capability
├── `pretool-claude-config-guard.py` - PreToolUse Hook: Claude config (.claude/hooks + .claude/commands) protection
├── `pretool-commit-dispatch-attest.py` - Writes `<state-dir>/claude-commit-dispatch-<sid>-<nonce>.json` when, and only
├── `pretool-cp-checkin.py` - cp-state file read (the write is scripts/spec-check.py's `register`)
├── `pretool-cp-state-write-guard.py` - Cycle-3 slim form (2026-05-14): Bash-extractor removed — 22-form adversarial
├── `pretool-dispatch-gate.py` - The rules run in this order, each as its own hook would run alone (its switch, its
├── `pretool-do-block-subagents.py` - PreToolUse hook: block Agent/Task dispatch from the MAIN agent while a /do
├── `pretool-git-privilege-guard.py` - PreToolUse Hook: Agent git-privilege guard
├── `pretool-gitignore-preflight.py` - pretool-gitignore-preflight.py — PreToolUse hook (matcher: Agent)
├── `pretool-grep-backtrack-guard.py` - ROOT-CAUSE BACKGROUND (verified ground truth, 2026-06-15 host OOM)
├── `pretool-layer-escalation-check.sh` - STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
├── `pretool-layer-match-gate.sh` - STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
├── `pretool-obligation-gate.py` - WHY THIS HOOK EXISTS:
├── `pretool-orchestrator-gate.py` - PreToolUse Hook: Orchestrator Gate (Unified)
├── `pretool-orchestrator-prompt-purity.py` - PreToolUse hook: Orchestrator Prompt Purity
├── `pretool-overnight-hook-guard.py` - PreToolUse Hook: Overnight session file modification guard
├── `pretool-push-analyst-grant-guard.py` - PreToolUse (matcher Bash): exit-0 stub kept at its registered path (D15).
├── `pretool-quality-gate.py` - PreToolUse Hook: Quality gate for Write/Edit operations (advisory)
├── `pretool-read-size-guard.py` - PreToolUse Hook: Read Size Guard
├── `pretool-runcode-watchdog.py` - PreToolUse Hook: Start timeout watchdog for browser_run_code
├── `pretool-spec-block-foreground-agent.py` - PreToolUse Hook: Block foreground Agent during an active /spec Interview
├── `pretool-subagent-code-block.py` - It printed a stderr warning when a subagent whose role does not resolve to dev
├── `pretool-subagent-enforce.py` - PreToolUse:Agent Hook — Contract-driven role/pipeline enforcement (G1)
├── `pretool-todo-validate.py` - PreToolUse Hook: Validate TodoWrite input BEFORE execution
├── `pretool-tool-policy.py` - tool-policy.v1.json for all subagents
├── `pretool-workflow-gate.py` - PreToolUse Hook: Require TodoWrite/TodoRead acknowledgment before other tools
├── `pretool-worktree-guard.sh` - PreToolUse hook: Detect stale agent worktrees before ANY tool call
├── `pretool-wrapper-userintent.py` - fix-4 (Cycle-2, spec-20260604-204954 §7.4). The /stop slash command releases
├── `pretool-write-gate.py` - It replaces seven parallel hooks (hooks-audit O4) with one process: the rules of
├── `pretool-write-guard.sh` - STUB: settings.json no longer registers it (P12); hooks/pretool-write-gate.py runs its checks as the
├── `prompt-workflow.py` - UserPromptSubmit Hook: Checklist Injection for Slash Commands
├── `protection-status.sh` - protection-status.sh - Display protection status for all git repositories
├── `pull.sh` - pull.sh - Executable version of /pull command
├── `push.sh` - push.sh - Executable version of /push command
├── `QUICKSTART.md` - Quick Start — the hooks layer
├── `session-git-init.sh` - Ensure Git Repository Hook for Claude Code
├── `session-gitignore-propagate.sh` - SessionStart hook: keep the harness's runtime directories out of a product repo's git status.
├── `session-info.sh` - session-info.sh — SessionStart: the session's directory, git state and project metadata, for the model.
├── `session-promote-hook.sh` - Description: SessionStart hook that promotes a cold session back to ramdisk.
├── `session-scratch-init.sh` - session-scratch-init.sh — SessionStart hook (Scratch Lifecycle Contract
├── `session-tmpfs-banner.sh` - session-tmpfs-banner.sh — SessionStart hook (6th in the SessionStart hooks block).
├── `sessionend-scratch-sweep.sh` - sessionend-scratch-sweep.sh — SessionEnd hook (Scratch Lifecycle Contract
├── `start-fswatch-all.sh` - start-fswatch-all.sh - Start fswatch monitoring for all important repositories
├── `stop-cleanup-allowlist.sh` - Stop Hook: reap every /allow grant the reader rejects at turn end.
├── `stop-command-gate.py` - The Stop coordinator's completion phase runs it with its mode
├── `stop-completion-gate.py` - blocked compliant /dev Stops with GATE_ERROR and its only release was a
├── `stop-do-report-gate.py` - It held a /do session's Stop until the do-report the consent sidecar named had
├── `stop-launch.py` - stderr. When the coordinator cannot decide (another exit, a timeout, a launch error, a missing
├── `stop-obligation-gate.py` - It re-validated, at the orchestrating session's Stop, the json artifacts its
├── `stop-overnight-timelock.py` - It blocked the session's Stop while its overnight window was open, then after
├── `stop-spec-coverage-enforce.py` - It ran spec-verify.py on the views of the spec the /spec session last wrote, at
├── `stop-workflow-coordinator.py` - LANE-B (20260808-035658) M4/M7, P5 R9: run by hooks/stop-launch.py (directly by a session that
├── `stop.sh` - stop.sh - wrapper for /stop slash command
├── `subagent-stop-diff-check.sh` - STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
├── `subagent-stop-guard-integrity.sh` - STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
├── `subagentstop-artifact-contract-enforce.py` - The stopping subagent's own dispatch obligation (hooks/lib/obligation.py)
├── `subagentstop-codex-enforce.py` - Activation logic:
├── `subagentstop-cp-enforce.py` - Description: SubagentStop hook for spec checkpoint enforcement (W6).
├── `subagentstop-e2e-enforce.py` - Activation logic:
├── `subagentstop-producer-gate.py` - The rules run in this order, each as its own hook would run alone (its switch, its
├── `subagentstop-restart-track.py` - SubagentStop: persist response evidence for a /restart-resumed agent.
├── `userprompt-bulk-commit-capability.py` - human prompt, NOT from an LLM-emitted Bash command
├── `userprompt-consent-allowlist.sh` - UserPromptSubmit Hook: parse `/allow <pattern>` and write a single-use
├── `userprompt-doc-sync-check.py` - UserPromptSubmit Hook: Periodic file deletion detection for doc-sync
├── `userprompt-restart-authorize.py` - the /dev-overnight session's own wake (lib.overnight.WAKE_PROMPT) inside its open span
├── `userprompt-tmpfs-pressure.sh` - userprompt-tmpfs-pressure.sh — UserPromptSubmit hook (4th block, appended).
└── `userprompt-usage-snapshot.py` - Passively injects a per-account usage snapshot (available/exhausted status,
```
<!-- /AUTO:index-stats -->

---
*Auto-generated by doc-sync hook.*