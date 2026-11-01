# tests

<!-- AUTO:index-stats -->
*Last updated: 2026-10-29T08:07:26Z*
**Total entries**: 138
**Convention**: kebab

## Tree
```
tests/
├── artifact_graph/
│   ├── `__main__.py` - ``python -m tests.artifact_graph <tree> <output.jsonl>``.
│   ├── `check.py` - `derive(tree, static, runs)` joins the static half (static_half.derive) and the
│   ├── `declarations.py` - the command files, the schemas' ids and enums, settings.json's hook
│   ├── `mdscan.py` - templates and the text a command shows the owner
│   ├── `model.py` - Every scanner appends plain facts to one `Findings`; `static_half.derive` turns
│   ├── `patterns.py` - The static half evaluates path expressions into *templates*: plain text in which
│   ├── `pyscan.py` - For every module it evaluates path expressions (string literals, f-strings,
│   ├── `runtime.py` - Every driver under tests/replay/drivers/ is replayed, each variant it offers,
│   ├── `shparse.py` - dependency beyond the standard library
│   ├── `shscan.py` - Words are evaluated into the same templates as Python values (variables by
│   ├── `static_half.py` - `derive(tree)` reads one harness tree and returns every record the static
│   ├── `test_check.py` - Each test builds a small harness-shaped tree, derives the static half on it and
│   ├── `test_rule2.py` - Each test builds a small harness-shaped tree, derives the static half on it and runs the check's
│   ├── `test_static_half.py` - Each test builds a small harness-shaped tree under tmp_path and checks the
│   └── `values.py` - A value is one of:
├── fixtures/
│   ├── late_repair_golden/
│   │   ├── `complete.json` - JSON config: artifact_paths, canonical_dev_report, checks, checks_not_applicable, commit_whitelist_artifacts
│   │   ├── `fanout.json` - JSON config: artifact_paths, canonical_dev_report, checks, checks_not_applicable, commit_whitelist_artifacts
│   │   ├── `mixed_integrity.json` - JSON config: artifact_paths, canonical_dev_report, checks, checks_not_applicable, commit_whitelist_artifacts
│   │   └── `qa_only.json` - JSON config: artifact_paths, canonical_dev_report, checks, checks_not_applicable, commit_whitelist_artifacts
│   ├── `canary-tool-policy.v1.json` - JSON config: _fixture, _purpose, _contract, policy_version, default_action
│   ├── `paseo-usage-envelope-20260828.json` - JSON config: _comment, type, message
│   └── `paseo_cron_vendor_vectors.json` - JSON config: _what, provenance, positive, negative, horizon
├── instructions/
│   ├── `execution-guide.md` - AI Test Execution Guide
│   └── `validation-guide.md` - AI-Driven Validation Guide
├── replay/
│   ├── drivers/
│   │   ├── `close.py` - (drivers/dev.py), after /do (drivers/do.py) or after /dev-command (drivers/dev_command.py, when
│   │   ├── `commit.py` - (drivers/close.py) of a /dev, /do or /dev-command task, or as `/commit --auto`
│   │   ├── `dev.py` - and the fan-out cycle (N > 1 lanes, "Requirement Decomposition & Fan-Out")
│   │   ├── `dev_command.py` - The main agent types `/dev-command <requirement>`: a new project slash command, the kind of
│   │   ├── `do.py` - (drivers/close.py) and /commit of it (drivers/commit.py)
│   │   ├── `redev.py` - tree under test; P1b D22: /redev is /dev when saving context, minted a fresh task id exactly as /...
│   │   ├── `smoke.py` - One session: SessionStart, one plain prompt, a few ordinary main-agent tool
│   │   └── `spec.py` - commands/spec.md, commands/spec-update.md and agents/spec.md of the tree under test
│   ├── `__main__.py` - `python -m tests.replay ...`: see cli.py.
│   ├── `agents.py` - A pipeline driver renders a dispatch prompt from the tree under test (its
│   ├── `cli.py` - python -m tests.replay build --tree T --sandbox SB
│   ├── `cmdtext.py` - Drivers never hard-code a block's text: they take it, at run time, from the
│   ├── `differential.py` - A reader decides on an artifact when re-running its recorded invocation with
│   ├── `hookrun.py` - Selection follows the planning kit's runhook.py: a matcher that is empty or "*"
│   ├── `inner.py` - cli.py starts it as `python -m replay.inner <config.json>` from the sandbox's
│   ├── `norm.py` - A replay's own values (session ids, agent ids, tool-use ids, task ids, lanes,
│   ├── `pipeline.py` - An Orchestrator plays the main agent of one typed command, following the
│   ├── `replay.py` - A driver gets a Replay and works through Sessions and Actors (the main agent,
│   ├── `roles.py` - Each helper returns an Act.work callable, work(sub, brief, player) -> content,
│   ├── `sandbox.py` - One scratch root holds everything a replay touches:
│   ├── `schemagen.py` - A simulated subagent writes each JSON artifact its obligation declares from the
│   └── `trace.py` - The replay runs under `strace -f --seccomp-bpf -z -y` tracing opens (with
├── score-inject-contract/
│   └── `test-inject-branches.sh` - Description: Verify scripts/score-inject.sh emits INJECTION_PROOF block with
├── score-lifecycle-contract/
│   └── `test-lifecycle-cas.sh` - Description: Verify CAS and append-only invariants for scripts/score-update.sh and
├── scripts/
│   ├── `validate-checklist-completeness.py` - Validator: validate-checklist-completeness
│   ├── `validate-chinese-content.py` - Validator: validate-chinese-content
│   ├── `validate-claude-md-protection.py` - Validator: validate-claude-md-protection
│   ├── `validate-debug-file-age.py` - Validator: validate-debug-file-age
│   ├── `validate-file-naming.py` - Validator: validate-file-naming
│   ├── `validate-optionality-language.py` - Validator: validate-optionality-language
│   ├── `validate-step-numbering.py` - Validator: validate-step-numbering
│   ├── `validate-todowrite-requirement.py` - Validator: validate-todowrite-requirement
│   ├── `validate-venv-usage.py` - Validator: validate-venv-usage
│   └── `validate-workflow-json-cleanup.py` - Validator: validate-workflow-json-cleanup
├── `_dev_lifecycle_fixtures.py` - NOT a test file itself (no test_ prefix, not collected by pytest). Imported by
├── `_late_repair_fixtures.py` - Not collected by pytest (leading underscore).  Builds four representative
├── `fresh-clone-bootstrap-smoke.sh` - Description: Fresh-clone bootstrap smoke — proves "core is runnable + guards engaged"
├── `test_ac_deviation_fanout_consumer.py` - records and the lifecycle presentation of ``pass_with_exceptions``
├── `test_ac_deviation_record_chain.py` - A dev report that legitimately records an acceptance-criteria deviation is
├── `test_aggregate_dev_report.py` - Unit tests for scripts/aggregate-dev-report.py
├── `test_aggregate_dev_report_superseded_rounds.py` - aggregate dev-report's ownership-completeness check over a multi-lane,
├── `test_apply_permissions.py` - /dev and /dev-command apply the permissions QA validated with the line their permission step
├── `test_bash_write_targets_verb_narrowing.py` - The library used to read a word that merely begins `cp-`/`mv-` (a checkpoint id such as `cp-01`, a
├── `test_bootstrap_init.py` - Every case runs in its own temporary clone of this repository, synced to the
├── `test_candidate_tree.py` - Every test builds its own throwaway git repository. None of them reads this
├── `test_changelog_analyst_declaration_categories.py` - `agents/changelog-analyst.md` decides what a cycle commits by reading declaration
├── `test_changelog_analyst_files_landed_whole_toctou.py` - `files_landed_whole` TOCTOU-safe stage-then-verify sequence (currently at
├── `test_changelog_analyst_required_to_ship_sourcing.py` - unobtainable declaration must not be silently read as an empty one
├── `test_checkpoint_provenance.py` - These modes are DORMANT: no command, agent definition, or hook invokes them by
├── `test_clean_orchestrator_merge.py` - clean-merge-reports reads the three inspector reports of the request the Step 3 context
├── `test_close_report_append.py` - failure semantics (round-7 CRITICAL fix, ticket dev-20260919-135733)
├── `test_codex_workflow_gate.py` - Regression tests for Codex-native workflow-plan compatibility.
├── `test_commit_multi_repo_plan.py` - Python script
├── `test_commit_sh_reachability.py` - commands/dev-overnight.md:1561 previously called a bare, unqualified
├── `test_completeness_channel_invariant.py` - One defect with a producer half and a consumer half:
├── `test_completeness_span_accounting.py` - halves on one code path
├── `test_conftest_hermetic.py` - conftest.py removes CLAUDE_PROJECT_DIR, PASEO_CONFIG_DIR, CLAUDE_HOME, CODEX_HOME,
├── `test_declared_vocab_readers.py` - (P1b row 19 rule 7): the chain resolver's disclosed-exception
├── `test_dev_artifact_chain_consumer_contracts.py` - Contract tests for shared /dev artifact-chain consumers.
├── `test_dev_todo_accounting.py` - Python script
├── `test_empty_old_string_diagnosis.py` - A real cycle emitted twenty-one ledger entries whose `old` was the empty string
├── `test_git_auto_push_opt_in.py` - Guards D1: nothing pushes outside /push unless GIT_AUTO_PUSH=1. Four code paths
├── `test_git_clean_guard_vectors.py` - The pre-clean WIP snapshot guard (task dev-20260719-150041-c, lane r03-c) is
├── `test_graphify_enrich_outputs.py` - The script reads the context file it is given and never writes it; it writes the run
├── `test_graphify_scripts.py` - tests/test_graphify_scripts.py — smoke tests for scripts/graphify_lib.py
├── `test_graphify_workflow_contract.py` - tests/test_graphify_workflow_contract.py — contract tests for graphify agent registration
├── `test_hero_advance_cross_check.py` - tools/demo/audit.mjs measures a line's rendered right edge on a fixed monospace grid, using
├── `test_interruption_signals.py` - Every banner asserted here was measured in the real transcript corpus under
├── `test_landing.py` - render-settings land, run from hooks/auto-commit.sh), migrate's push exclusion and the settings
├── `test_late_repair_driftfree_effective_state.py` - scripts/late-repair-controller.py's ``resolve_effective_report_state`` is the
├── `test_late_repair_route.py` - Covers AC-7..AC-11, AC-13, AC-14 (spec-20260907-115508-lawful-commit-channel.md,
├── `test_no_artificial_lifecycle_ceremony.py` - Prevent host metadata ceremonies from becoming ordinary lifecycle gates.
├── `test_overnight_guard_in_place_git.py` - Defect (2026-08-09): `hooks/pretool-overnight-hook-guard.py` blocked EVERY git
├── `test_overnight_loop_tz.py` - Verifies the overnight loop hook compares end_time correctly against the
├── `test_parent_cycle_claimant_reader.py` - THE DEFECT.  Admission to a cycle's ownership-completeness claimant set was
├── `test_paseo_daemon_ledger.py` - MANDATORY pytest facade for lane 20260828-112025-b: collects EVERY test
├── `test_paseo_daemon_timers.py` - scripts/paseo-daemon-timers.py (task 20260926-111239)
├── `test_paseo_usage_read.py` - MANDATORY pytest facade for lane 20260828-112025-b: collects EVERY test
├── `test_private_literal_rule.py` - pre-commit hook hooks/git-hooks/pre-commit
├── `test_prompt_workflow_injection_cadence.py` - The defect: ``build_overnight_continuation`` emitted ONE payload at ONE cadence
├── `test_prompt_workflow_liveness_tz.py` - Two defects, both reproduced before this suite was written:
├── `test_public_core_residue_gate.py` - These are the discriminating controls for the "Make CI FAIL (not advisory) on
├── `test_refusal_record_consumers.py` - This is the module named BY NAME as `check.cli_run.harness` by AC12 and AC14 of
├── `test_release_pipeline_contract.py` - verifier
├── `test_resolve_dev_artifact_chain.py` - Focused tests for the read-only /dev artifact-chain resolver.
├── `test_resolve_spec_artifacts.py` - resolver) + the static centralization lint (AC-B4 cases 1-12, task 20260530-092123)
├── `test_restart_command.py` - End-to-end unit coverage for the human-only /restart recovery protocol.
├── `test_score_log.py` - scripts/score-update.sh and scripts/score-inject.sh both call read_lines in place
├── `test_settings_filter.py` - applied layers, the machine-form renderer, the doctor and pre-commit checks, and the owner
├── `test_settings_load.py` - take its verdict which no other test runs: the claude_home probes, installer.py's plan, and the two
├── `test_spec_check_agent_id_guard.py` - Lane b of task 20260921-134709. Self-contained and subprocess based: one scratch
├── `test_spec_check_closed_slot.py` - task 20260921-134709)
├── `test_spec_check_concurrent_marking.py` - also when hooks/pretool-cp-checkin.py runs it on a subagent's Read (harness backlog #97)
├── `test_spec_update_command_contracts.py` - Contracts for the live ``/spec-update`` command policy and its history entry.
├── `test_spec_verify.py` - The overlap and uniqueness rules do not count the lines the split rules route into
├── `test_spec_write.py` - Each test runs the script as a subprocess against a throw-away project under
├── `test_specialist_yield.py` - Tests use a tmp dir for the yield log and the bundled production policy file
├── `test_stage_owned_hunks_boundary.py` - content-anchor-retry boundary/coordinate-space defect (task 20260912-015952)
├── `test_subagentstop_e2e_enforce.py` - A QA dispatch that carries an obligation is judged on exactly the qa-report
├── `test_todo_md_sync.py` - Regression tests for the session-start todo/Markdown drift detector.
├── `test_tool_policy_note_fail_closed.py` - hooks/pretool-tool-policy.py refuses a Bash write target with exit 2 and then
├── `test_verify_claims_tracked_form.py` - On an initialised home the claude-settings filter leaves the machine form in the
├── `test_write_qa_mode.py` - Each QA dispatch's obligation now declares the report it owes, so no qa_mode
├── `TESTING.md` - Test Topology & Runner Map (authoritative)
└── `verify-stop-spec-session-isolation.sh` - QA verification harness for stop-spec-coverage-enforce.py session isolation fix.
```
<!-- /AUTO:index-stats -->

---
*Auto-generated by doc-sync hook.*