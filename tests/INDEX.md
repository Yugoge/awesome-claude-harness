# tests

<!-- AUTO:index-stats -->
*Last updated: 2026-11-10T08:16:38Z*
**Total entries**: 222
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
│   ├── `shards.py` - One 4-CPU runner needs about 3,000 s for every traced replay and E1's differential: twice E2's
│   ├── `shparse.py` - dependency beyond the standard library
│   ├── `shscan.py` - Words are evaluated into the same templates as Python values (variables by
│   ├── `static_half.py` - `derive(tree)` reads one harness tree and returns every record the static
│   ├── `test_check.py` - Each test builds a small harness-shaped tree, derives the static half on it and
│   ├── `test_mutations.py` - Each test copies the tree under test (this checkout) to a scratch directory,
│   ├── `test_rule1_7.py` - declared artifact) and rule (7) (a list that repeats a declaration)
│   ├── `test_rule2.py` - Each test builds a small harness-shaped tree, derives the static half on it and runs the check's
│   ├── `test_rule4_6.py` - mutation), rule (5) (the chain function's output used verbatim) and rule (6) (a deciding read
│   ├── `test_sandbox_template.py` - A copied sandbox must be the built one as far as a replay can tell: the same
│   ├── `test_shards.py` - The plan is computed from the drivers present at run time: every driver lands
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
├── lint/
│   ├── `__main__.py` - python3 -m tests.lint [--tree DIR] [--check NAME ...]: print the findings, exit 1 on any.
│   ├── `checks.py` - The six checks by name, in the order the P12 plan lists them.
│   ├── `hooks.py` - What reaches the model (the CLI's hook contract): the stderr of an exit 2; a JSON object on
│   ├── `prompts.py` - The four prompt checks: hook strength, dead references, repeated blocks, emphasis.
│   ├── `test_lint_checks.py` - These run in the ordinary suite. The checks on this repository's own tree are in
│   ├── `test_lint_tree.py` - Collected only under HARNESS_LINT=1, which the baseline workflow's lint step sets; the
│   └── `tree.py` - The settings and ledger parsing is scripts/check-enforcement-evidence.py's own (the gate
├── replay/
│   ├── bin/
│   │   └── `bwrap` - bwrap file
│   ├── drivers/
│   │   ├── `_codex.py` - A driver variant that runs QA's `--codex` path (drivers/close.py `codex-flip-items`, `codex-endle...
│   │   ├── `_deadend.py` - then take the same actor's next action, the one the gate's own text names
│   │   ├── `_home.py` - The owner's own session in ~/.claude: SessionStart, a read-only question about the harness, the m...
│   │   ├── `_pathrule.py` - replayed at the hooks that read them, in the kit of the tree under test (`--driver _pathrule`)
│   │   ├── `clean.py` - test, read at run time, up to the cleaner's commit and the completion report
│   │   ├── `close.py` - (drivers/dev.py), after /do (drivers/do.py) or after /dev-command (drivers/dev_command.py, when
│   │   ├── `commit.py` - (drivers/close.py) of a /dev, /do or /dev-command task, after a /dev that was never closed, or as
│   │   ├── `dev.py` - and the fan-out cycle (N > 1 lanes, "Requirement Decomposition & Fan-Out")
│   │   ├── `dev_command.py` - The main agent types `/dev-command <requirement>`: a new project slash command, the kind of
│   │   ├── `do.py` - (drivers/close.py) and /commit of it (drivers/commit.py)
│   │   ├── `merge.py` - Before the session the owner, in their own terminal (no hook sees it), commits on the toy's main
│   │   ├── `overnight.py` - 1-pipeline session from launch to its Stop after end_time (P1c's compliant /dev-overnight scenari...
│   │   ├── `push.py` - after a /commit that landed (drivers/commit.py, after drivers/do.py or drivers/dev.py and drivers...
│   │   ├── `receipt.py` - registered Stop hooks with both trust keys in the replay's environment
│   │   ├── `redev.py` - tree under test; P1b D22: /redev is /dev when saving context, minted a fresh task id exactly as /...
│   │   ├── `smoke.py` - One session: SessionStart, one plain prompt, a few ordinary main-agent tool
│   │   └── `spec.py` - commands/spec.md, commands/spec-update.md and agents/spec.md of the tree under test
│   ├── `__main__.py` - `python -m tests.replay ...`: see cli.py.
│   ├── `agents.py` - A pipeline driver renders a dispatch prompt from the tree under test (its
│   ├── `cli.py` - python -m tests.replay build --tree T --sandbox SB
│   ├── `cmdtext.py` - Drivers never hard-code a block's text: they take it, at run time, from the
│   ├── `conftest.py` - Every test that replays asks for the `replays` fixture with a marker naming what it needs:
│   ├── `differential.py` - A reader decides on an artifact when re-running its recorded invocation with
│   ├── `faults.py` - --arg fault=<kind>@<label glob>[=<what>][;<kind>@<label glob>[=<what>]...]
│   ├── `hookrun.py` - Selection follows the planning kit's runhook.py: a matcher that is empty or "*"
│   ├── `inner.py` - cli.py starts it as `python -m replay.inner <config.json>` from the sandbox's
│   ├── `landing.py` - The CLI keeps the hook commands it loaded at session start (the settings file a replay reads once,
│   ├── `norm.py` - A replay's own values (session ids, agent ids, tool-use ids, task ids, lanes,
│   ├── `pipeline.py` - An Orchestrator plays the main agent of one typed command, following the
│   ├── `recovery.py` - --arg fault=cut@<label glob>     F5, F5f: after the first step of a subagent whose label matches
│   ├── `replay.py` - A driver gets a Replay and works through Sessions and Actors (the main agent,
│   ├── `roles.py` - Each helper returns an Act.work callable, work(sub, brief, player) -> content,
│   ├── `routing.py` - No hook blocks here: the gap is what /close's disposition call (Step 0) or /commit's (Step 3) pri...
│   ├── `sandbox.py` - One scratch root holds everything a replay touches:
│   ├── `schemagen.py` - A simulated subagent writes each JSON artifact its obligation declares from the
│   ├── `scorelog.py` - Driver argument (cli.py --arg K=V; inner.py calls resweep() when it is given, after the driver ra...
│   ├── `sites.py` - Nothing here lists a site, a hook or a class. Enumerator reads settings.json and follows each
│   ├── `suite.py` - A scenario names one of P1b's drivers (tests/replay/drivers/) and its arguments. run() replays it
│   ├── `test_a20.py` - Every compliant scenario runs with the gate blocking: test_pipelines.py's armed settings set
│   ├── `test_bwrap_stand_in.py` - An in-place /dev-overnight launch refuses where `bwrap --ro-bind / / -- true` cannot run
│   ├── `test_codex_loop.py` - Each replay plays QA's `--codex` path against a stub Codex (tests/replay/drivers/_codex.py). The ...
│   ├── `test_faults.py` - is repaired at that producer's next round with no human action; the pipeline reaches its terminal
│   ├── `test_kept_first_line.py` - hookrun keeps a hook's output tail; for a long refusal that tail is the echoed
│   ├── `test_live_arming.py` - this tree's files
│   ├── `test_live_landing.py` - keep running with the hook list they loaded; nothing new may block a running session or an in-fli...
│   ├── `test_no_dead_end.py` - (i) The blocking sites are enumerated when the test runs (tests/replay/sites.py), never read from a
│   ├── `test_pipelines.py` - reaches its terminal, with the tree's settings ("shipped") and armed (G1-G3 block)
│   ├── `test_push_holds.py` - Each replay types /push after the owner's commit and the token its one writer wrote for it
│   ├── `test_refusals.py` - Each replay reaches one refusal of commands/merge.md or commands/push.md, played by its driver from
│   ├── `test_regressions.py` - R-N1 (review N1 of P7b's PR, X9) and R-V1 (reviews V1-1 and NV-1) are script-level replays. A
│   ├── `test_run_to_run.py` - The artifact check (tests/test_artifact_graph.py) derives its relations from traced replays,
│   ├── `test_score_dispatch.py` - The real hooks run under the shipped settings in a sandbox whose score log starts with the rows a driver argument seeds; the...
│   ├── `test_score_replay.py` - The real hooks run under the shipped settings in a sandbox that has its own config directory; the...
│   ├── `test_trace_reduce.py` - Each case is a run-to-run difference two replays of one driver showed under load:
│   ├── `test_typed_corrections.py` - Each replay types the command with an argument that names nothing: /close of a ticket path of ano...
│   ├── `trace.py` - The replay runs under `strace -f --seccomp-bpf -z -y` tracing opens (with
│   └── `wake.py` - Modeled CLI behaviour and its sources (none of it measured on a harness host):
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
├── `test_ac_deviation_fanout_consumer.py` - lanes that stop short of ``completed`` and the lifecycle row of a chain
├── `test_ac_deviation_record_chain.py` - A dev report that records an acceptance-criteria deviation is reported
├── `test_aggregate_dev_report.py` - Unit tests for scripts/aggregate-dev-report.py
├── `test_aggregate_dev_report_superseded_rounds.py` - aggregate dev-report's ownership-completeness check over a multi-lane,
├── `test_apply_permissions.py` - /dev and /dev-command apply the permissions QA validated with the line their permission step
├── `test_artifact_graph.py` - The check (tests/artifact_graph/check.py) replays every driver under
├── `test_auto_push_per_repo.py` - A repository's local git config harness.autoPush decides whether automatic pushes run for it;
├── `test_bash_write_targets_verb_narrowing.py` - The library used to read a word that merely begins `cp-`/`mv-` (a checkpoint id such as `cp-01`, a
├── `test_bootstrap_init.py` - Every case runs in its own temporary clone of this repository, synced to the
├── `test_candidate_tree.py` - Every test builds its own throwaway git repository. None of them reads this
├── `test_changelog_analyst_declaration_categories.py` - `agents/changelog-analyst.md` decides what a cycle commits by reading declaration
├── `test_changelog_analyst_required_to_ship_sourcing.py` - unobtainable declaration must not be silently read as an empty one
├── `test_checkpoint_provenance.py` - These modes are DORMANT: no command, agent definition, or hook invokes them by
├── `test_clean_orchestrator_merge.py` - clean-merge-reports reads the three inspection reports of the request the Step 3 context
├── `test_cleaner_discard.py` - Action Types table gives and prints a DISCARDED line whose recover command restores the file. The
├── `test_close_command_text.py` - commands/close.md as P4 decided it: one disposition call, in-turn questions, the native rating.
├── `test_close_rating_step_label.py` - P4-3: /close's rating step is "Step 4" (P4 R4, R7, R11, A3), not the "Step 3b" 376a9ae gave it.
├── `test_close_report_append.py` - failure semantics (round-7 CRITICAL fix, ticket dev-20260919-135733)
├── `test_close_report_append_lock_cleanup.py` - the append leaves no `.append-lock` file in the product repo (P10-36), mutual exclusion kept
├── `test_close_route_select_compat.py` - It answers the two calls origin/master's /close Step 0 makes (commands/close.md:296 on a7d3a9f, :...
├── `test_codex_workflow_gate.py` - Regression tests for Codex-native workflow-plan compatibility.
├── `test_commit_multi_repo_plan.py` - Python script
├── `test_commit_sh_reachability.py` - commands/dev-overnight.md:1561 previously called a bare, unqualified
├── `test_completeness_channel_invariant.py` - One defect with a producer half and a consumer half:
├── `test_completeness_span_accounting.py` - halves on one code path
├── `test_conftest_hermetic.py` - conftest.py removes CLAUDE_PROJECT_DIR, PASEO_CONFIG_DIR, CLAUDE_HOME, CODEX_HOME,
├── `test_declared_vocab_readers.py` - (P1b row 19 rule 7): the orphan-agent detector asks the command files
├── `test_dev_artifact_chain_consumer_contracts.py` - Contract tests for shared /dev artifact-chain consumers.
├── `test_dev_commands_no_phases.py` - Every requested outcome is delivered in the same cycle and the cycle ends only when all are done....
├── `test_dev_todo_accounting.py` - Python script
├── `test_discover_folders.py` - INDEX per discovered folder) leaves out the harness's own directories in a project: .claude (Claude
├── `test_disposition.py` - (scripts/resolve-dev-artifact-chain.py ``disposition`` and ``--disposition``)
├── `test_empty_old_string_diagnosis.py` - A real cycle emitted twenty-one ledger entries whose `old` was the empty string
├── `test_git_auto_push_opt_in.py` - Guards D1: nothing pushes outside /push unless GIT_AUTO_PUSH=1. Four code paths
├── `test_git_clean_guard_vectors.py` - The pre-clean WIP snapshot guard (task dev-20260719-150041-c, lane r03-c) is
├── `test_graphify_enrich_outputs.py` - graphify-query.py check their results against their schemas before writing (P10 A17)
├── `test_graphify_scripts.py` - tests/test_graphify_scripts.py — smoke tests for scripts/graphify_lib.py
├── `test_graphify_workflow_contract.py` - tests/test_graphify_workflow_contract.py — contract tests for graphify agent registration
├── `test_hero_advance_cross_check.py` - tools/demo/audit.mjs measures a line's rendered right edge on a fixed monospace grid, using
├── `test_hero_demo_state_dir.py` - The hero demo honours an absolute CLAUDE_STATE_DIR end to end.
├── `test_hook_rejection_retry.py` - A hook-rejected operation is never retried on the owner's answer alone: only their /allow grant (dev, paseo-daemon, clean); an operation no grant can let through is withdrawn, never left to the owner's own run.
├── `test_interruption_signals.py` - Every banner asserted here was measured in the real transcript corpus under
├── `test_iterate_failed_pipelines_compat.py` - It answers the call origin/master's /dev-overnight Step 17 makes (commands/dev-overnight.md:1384 ...
├── `test_landing.py` - render-settings land, run from hooks/auto-commit.sh), migrate's push exclusion and the settings
├── `test_late_repair_driftfree_effective_state.py` - scripts/late-repair-controller.py's ``resolve_effective_report_state`` is the
├── `test_late_repair_route.py` - Covers AC-7..AC-11, AC-13, AC-14 (spec-20260907-115508-lawful-commit-channel.md,
├── `test_launchdiff_durations.py` - tests/replay/launchdiff.py compares each launcher event's hooks with the old path, normalised.
├── `test_no_phases_agent_prompts.py` - Parallel lanes inside one /dev cycle stay. Sequential phases, deferred parts and "later cycle" pl...
├── `test_no_phases_spec_command.py` - Parallel lanes inside one cycle stay. A spec, a view or a hand-off note never splits a requested ...
├── `test_no_phases_spec_template.py` - Everything the user requested is done in the cycle; Section 7 lists the actions that
├── `test_overnight_guard_in_place_git.py` - Defect (2026-08-09): `hooks/pretool-overnight-hook-guard.py` blocked EVERY git
├── `test_overnight_loop_tz.py` - Verifies the overnight loop hook compares end_time correctly against the
├── `test_parent_cycle_claimant_reader.py` - THE DEFECT.  Admission to a cycle's ownership-completeness claimant set was
├── `test_paseo_daemon_ledger.py` - MANDATORY pytest facade for lane 20260828-112025-b: collects EVERY test
├── `test_paseo_daemon_timers.py` - scripts/paseo-daemon-timers.py (task 20260926-111239)
├── `test_paseo_usage_read.py` - MANDATORY pytest facade for lane 20260828-112025-b: collects EVERY test
├── `test_permission_coverage.py` - entry that covers it (P2 R6/R17, D14: entries are respelled, none granted or withdrawn)
├── `test_pre_commit_dev_command_files.py` - The fail-closed pre-commit hook (hooks/git-hooks/pre-commit) lets a commit stage the
├── `test_private_literal_rule.py` - pre-commit hook hooks/git-hooks/pre-commit
├── `test_prompt_workflow_injection_cadence.py` - The defect: ``build_overnight_continuation`` emitted ONE payload at ONE cadence
├── `test_prompt_workflow_liveness_tz.py` - Two defects, both reproduced before this suite was written:
├── `test_public_core_residue_gate.py` - These are the discriminating controls for the "Make CI FAIL (not advisory) on
├── `test_rating_view.py` - text, and commands/rating.md only runs that script
├── `test_readme_facts.py` - names its input when it is missing
├── `test_readme_regions.py` - the prose around them
├── `test_refusal_record_consumers.py` - This is the module named BY NAME as `check.cli_run.harness` by AC12 and AC14 of
├── `test_release_pipeline_contract.py` - verifier
├── `test_resolve_dev_artifact_chain.py` - Focused tests for the read-only /dev artifact-chain resolver.
├── `test_resolve_spec_artifacts.py` - resolver) + the static centralization lint (AC-B4 cases 1-12, task 20260530-092123)
├── `test_restart_command.py` - End-to-end unit coverage for the human-only /restart recovery protocol.
├── `test_score_events.py` - escaped and close_catch, and the observer
├── `test_score_log.py` - two renderers (owner summary, /rating view); and the reader's two callers
├── `test_session_index.py` - Each update-index call of scripts/lib/session_index.py's sync (the --cacheinfo one for a modified...
├── `test_settings_filter.py` - applied layers, the machine-form renderer, the doctor and pre-commit checks, and the owner
├── `test_settings_load.py` - take its verdict which no other test runs: the claude_home probes, installer.py's plan, and the two
├── `test_size_ratchet.py` - `--measure` counts the six metrics of a committed tree; `--check --budget-ref <rev>` holds HEAD to
├── `test_spec_check_agent_id_guard.py` - Lane b of task 20260921-134709. Self-contained and subprocess based: one scratch
├── `test_spec_check_closed_slot.py` - task 20260921-134709)
├── `test_spec_check_concurrent_marking.py` - also when hooks/pretool-cp-checkin.py runs it on a subagent's Read (harness backlog #97)
├── `test_spec_update_command_contracts.py` - Contracts for the live ``/spec-update`` command policy and its history entry.
├── `test_spec_verify.py` - The overlap and uniqueness rules do not count the lines the split rules route into
├── `test_spec_write.py` - Each test runs the script as a subprocess against a throw-away project under
├── `test_specialist_yield.py` - Tests use a tmp dir for the yield log and the bundled production policy file
├── `test_stage_owned_hunks_boundary.py` - content-anchor-retry boundary/coordinate-space defect (task 20260912-015952)
├── `test_step8_spec_update_markers.py` - COMMIT_STEP8_TRACE=1 emits the STEP8_* markers on stderr, and stage 4's unlinked spec is printed
├── `test_steps_clean_merge_approvals.py` - cleaner's context
├── `test_steps_codex_run.py` - Every test runs the real script against a stub wrapper in a temp dir (CODEX_ISO_BIN). No real cod...
├── `test_steps_commit_plan.py` - repositories and temporary report files (no network, nothing read from the owner's home)."""
├── `test_steps_merge_snapshot.py` - against temporary git repositories (no network, nothing read from the owner's home)."""
├── `test_steps_paseo_bootstrap.py` - The script is run for real, as a subprocess, with the ledger CLI and the timers CLI behind it
├── `test_steps_pull_run.py` - and its Graphify update, run for real against temporary git repositories with a local bare remote...
├── `test_steps_push_snapshot.py` - Every test runs the real script in a temporary git repository (no network, nothing read from the ...
├── `test_steps_spec_capture.py` - Every test runs the real script in a temp project with no network and no dependence on the runner...
├── `test_steps_spec_finalize.py` - Every test runs the real script in a temp project with no network and no dependence on the runner...
├── `test_steps_test_context.py` - The validation context keeps the shape agents/test-validator.md documents as its Input Format. Th...
├── `test_steps_test_prepare.py` - Each case runs the real script in a temporary project; nothing touches the runner's home or the n...
├── `test_steps_test_validators.py` - Step 5 used to end the command with `exit 1` on a missing folder or an empty validator set; the c...
├── `test_subagentstop_e2e_enforce.py` - A QA dispatch that carries an obligation is judged on exactly the qa-report
├── `test_test_command_routes.py` - /test's failure routes: no typed menu or exit option, and only executor statuses the executor emits (D23, D25).
├── `test_todo_md_sync.py` - Regression tests for the session-start todo/Markdown drift detector.
├── `test_todo_root.py` - A product whose scripts/todo/<command>.py and hooks/lib/close-verdict.py exist
├── `test_tool_policy_note_fail_closed.py` - hooks/pretool-tool-policy.py refuses a Bash write target with exit 2 and then
├── `test_verify_claims_tracked_form.py` - On an initialised home the claude-settings filter leaves the machine form in the
├── `test_write_qa_mode.py` - Each QA dispatch's obligation now declares the report it owes, so no qa_mode
├── `TESTING.md` - Test Topology & Runner Map (authoritative)
└── `verify-stop-spec-session-isolation.sh` - Checks stop-spec-coverage-enforce.py, an exit-0 stub: G2 checks the split at the spec subagent's stop.
```
<!-- /AUTO:index-stats -->

---
*Auto-generated by doc-sync hook.*