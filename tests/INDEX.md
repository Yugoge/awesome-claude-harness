# tests

<!-- AUTO:index-stats -->
*Last updated: 2026-10-05T11:07:46Z*
**Total entries**: 149
**Convention**: kebab

## Tree
```
tests/
├── fixtures/
│   ├── late_repair_golden/
│   │   ├── `complete.json` - JSON config: artifact_paths, canonical_dev_report, checks, checks_not_applicable, commit_whitelist_artifacts
│   │   ├── `fanout.json` - JSON config: artifact_paths, canonical_dev_report, checks, checks_not_applicable, commit_whitelist_artifacts
│   │   ├── `mixed_integrity.json` - JSON config: artifact_paths, canonical_dev_report, checks, checks_not_applicable, commit_whitelist_artifacts
│   │   └── `qa_only.json` - JSON config: artifact_paths, canonical_dev_report, checks, checks_not_applicable, commit_whitelist_artifacts
│   ├── `canary-tool-policy.v1.json` - JSON config: _fixture, _purpose, _contract, policy_version, default_action
│   ├── `paseo-usage-envelope-20260828.json` - JSON config: _comment, type, message
│   └── `paseo_cron_vendor_vectors.json` - JSON config: _what, provenance, positive, negative, horizon
├── generated/
│   └── `manifest.json` - JSON config: schema_version, kind, tasks
├── instructions/
│   ├── `execution-guide.md` - AI Test Execution Guide
│   └── `validation-guide.md` - AI-Driven Validation Guide
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
├── `test_aggregate_dev_report_hook_ledger.py` - ledger (backlog #122 M3): scripts/aggregate-dev-report.py's len(shards_info)
├── `test_aggregate_dev_report_superseded_rounds.py` - aggregate dev-report silently dropped a retried lane's superseded round(s)'
├── `test_bash_write_targets_verb_narrowing.py` - The library used to read a word that merely begins `cp-`/`mv-` (a checkpoint id such as `cp-01`, a
├── `test_candidate_tree.py` - Every test builds its own throwaway git repository. None of them reads this
├── `test_changelog_analyst_declaration_categories.py` - `agents/changelog-analyst.md` decides what a cycle commits by reading declaration
├── `test_changelog_analyst_files_landed_whole_toctou.py` - `files_landed_whole` TOCTOU-safe stage-then-verify sequence (currently at
├── `test_changelog_analyst_required_to_ship_sourcing.py` - unobtainable declaration must not be silently read as an empty one
├── `test_checkpoint_provenance.py` - These modes are DORMANT: no command, agent definition, or hook invokes them by
├── `test_close_report_append.py` - failure semantics (round-7 CRITICAL fix, ticket dev-20260919-135733)
├── `test_codex_workflow_gate.py` - Regression tests for Codex-native workflow-plan compatibility.
├── `test_commit_multi_repo_plan.py` - Python script
├── `test_commit_sh_reachability.py` - commands/dev-overnight.md:1561 previously called a bare, unqualified
├── `test_completeness_channel_invariant.py` - One defect with a producer half and a consumer half:
├── `test_completeness_span_accounting.py` - halves on one code path
├── `test_conftest_hermetic.py` - The root conftest drops the inherited variables that point a run at the runner's own project or home.
├── `test_dev_artifact_chain_consumer_contracts.py` - Contract tests for shared /dev artifact-chain consumers.
├── `test_empty_old_string_diagnosis.py` - A real cycle emitted twenty-one ledger entries whose `old` was the empty string
├── `test_generate_repair_map.py` - Covers AC-L8-01..04 and AC-L8-13 (docs/dev/acceptance-criteria-20260930-132644-l8.json)
├── `test_git_auto_push_opt_in.py` - GIT_AUTO_PUSH opt-in: checkpoint, post-commit, combined LFS hook, fswatch and session-git-init push only if it is 1
├── `test_git_clean_guard_vectors.py` - The pre-clean WIP snapshot guard (task dev-20260719-150041-c, lane r03-c) is
├── `test_graphify_scripts.py` - tests/test_graphify_scripts.py — smoke tests for scripts/graphify_lib.py
├── `test_graphify_workflow_contract.py` - tests/test_graphify_workflow_contract.py — contract tests for graphify agent registration
├── `test_hero_advance_cross_check.py` - tools/demo/audit.mjs measures a line's rendered right edge on a fixed monospace grid, using
├── `test_interruption_signals.py` - Every banner asserted here was measured in the real transcript corpus under
├── `test_late_repair_driftfree_effective_state.py` - scripts/late-repair-controller.py's ``resolve_effective_report_state`` is the
├── `test_late_repair_route.py` - Covers AC-7..AC-11, AC-13, AC-14 (spec-20260907-115508-lawful-commit-channel.md,
├── `test_no_artificial_lifecycle_ceremony.py` - Prevent host metadata ceremonies from becoming ordinary lifecycle gates.
├── `test_overnight_guard_in_place_git.py` - Defect (2026-08-09): `hooks/pretool-overnight-hook-guard.py` blocked EVERY git
├── `test_overnight_loop_tz.py` - Verifies the overnight loop hook compares end_time correctly against the
├── `test_parent_cycle_claimant_reader.py` - THE DEFECT.  Admission to a cycle's ownership-completeness claimant set was
├── `test_paseo_daemon_ledger.py` - MANDATORY pytest facade for lane 20260828-112025-b: collects EVERY test
├── `test_paseo_daemon_timers.py` - scripts/paseo-daemon-timers.py (task 20260926-111239)
├── `test_paseo_usage_read.py` - MANDATORY pytest facade for lane 20260828-112025-b: collects EVERY test
├── `test_prompt_workflow_injection_cadence.py` - The defect: ``build_overnight_continuation`` emitted ONE payload at ONE cadence
├── `test_prompt_workflow_liveness_tz.py` - Two defects, both reproduced before this suite was written:
├── `test_public_core_residue_gate.py` - These are the discriminating controls for the "Make CI FAIL (not advisory) on
├── `test_refusal_record_consumers.py` - This is the module named BY NAME as `check.cli_run.harness` by AC12 and AC14 of
├── `test_release_pipeline_contract.py` - verifier
├── `test_repair_map_call_site_coverage.py` - (ticket-20261001-161041-r19)
├── `test_repair_orchestrate.py` - Covers AC-L8-05..08 and AC-L8-14..16
├── `test_resolve_dev_artifact_chain.py` - Focused tests for the read-only /dev artifact-chain resolver.
├── `test_resolve_spec_artifacts.py` - resolver) + the static centralization lint (AC-B4 cases 1-12, task 20260530-092123)
├── `test_restart_command.py` - End-to-end unit coverage for the human-only /restart recovery protocol.
├── `test_spec_check_agent_id_guard.py` - Lane b of task 20260921-134709. Self-contained and subprocess based: one scratch
├── `test_spec_check_closed_slot.py` - task 20260921-134709)
├── `test_spec_check_concurrent_marking.py` - hooks/pretool-cp-checkin.py (harness backlog #97)
├── `test_specialist_yield.py` - Tests use a tmp dir for the yield log and the bundled production policy file
├── `test_stage_owned_hunks_boundary.py` - content-anchor-retry boundary/coordinate-space defect (task 20260912-015952)
├── `test_subagentstop_e2e_enforce.py` - Backlog: dev-20260923-083731 -- widen _find_latest_qa_report's correlation
├── `test_todo_md_sync.py` - Regression tests for the session-start todo/Markdown drift detector.
├── `test_tool_policy_note_fail_closed.py` - An exception inside the tool-policy refusal note never turns exit 2 into an allow
├── `TESTING.md` - Test Topology & Runner Map (authoritative)
└── `verify-stop-spec-session-isolation.sh` - QA verification harness for stop-spec-coverage-enforce.py session isolation fix.
```
<!-- /AUTO:index-stats -->

---
*Auto-generated by doc-sync hook.*