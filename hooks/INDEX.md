# hooks

<!-- AUTO:index-stats -->
*Last updated: 2026-11-23T13:40:59Z*
**Total entries**: 577
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
│   ├── `pre-commit` - pre-commit file
│   └── `pre-push` - pre-push file
├── git-keystone/
│   └── `reference-transaction` - reference-transaction file
├── lib/
│   ├── runtime_guard/
│   │   ├── `_core.py` - This module contains ZERO project identifiers. Every project-specific name
│   │   ├── `anchor.py` - The cleanly-extractable leaf subset of the HEAD-AGNOSTIC P0 anchor scan
│   │   ├── `config.py` - Depends on pathmatch (`_normalize_path`, `_strip_quotes`) + stdlib; references nothing from _core...
│   │   ├── `constants.py` - Dependency LEAF: defines only literal frozenset/dict constants, imports nothing,
│   │   ├── `context.py` - `_core.evaluate` computes a small set of per-EVALUATION inputs ONCE — the
│   │   ├── `find_cmds.py` - Depends on pathmatch (`_strip_quotes`, `_glob_to_segment_regex`,
│   │   ├── `git_cmds.py` - Depends on pathmatch (`_strip_quotes`, `_expand_leading_home`) +
│   │   └── `pathmatch.py` - Depends only on the stdlib and owns `_strip_quotes`; references nothing from
│   ├── write_gate/
│   │   ├── `overwrite.py` - The Python form of hooks/pretool-write-guard.sh, decision for decision and message for
│   │   └── `overwrite_scope.py` - The overwrite rule (lib/write_gate/overwrite.py) refuses a Write onto an existing file; this
│   ├── `agent_cycle.py` - producer (posttool-codex-skill-ledger.py) and the hooks that read a cycle's
│   ├── `agent_resolver.py` - Refactored from pretool-subagent-code-block.py::_find_agent_type so that
│   ├── `agent_returns.py` - the one reading of whether a dispatch has returned, for every hook that asks
│   ├── `aggregate_rebuild.py` - One staleness test and one rebuild, the aggregator's own (scripts/aggregate-dev-report.py
│   ├── `allowlist.py` - The /allow grant's one writer (write_sentinel_grant), its one release decision
│   ├── `attribution_journal.py` - Capture side (used by pretool-attribution-pre.py / posttool-attribution-post.py):
│   ├── `auto_push.sh` - auto_push.sh -- harness_auto_push, the one reader of the per-repository push switch.
│   ├── `bash_active_syntax_census.py` - WHY THIS MODULE EXISTS (the "completeness obligation").  A removal policy whose
│   ├── `bash_execution_boundary.py` - THE ALGEBRA.  Every execution-bearing
│   ├── `bash_read_only.py` - ``is_read_only(command)`` is True only when every simple command in ``command``
│   ├── `bash_safety_rules.py` - Usage: bash_safety_rules.py <hooks dir>  (the PreToolUse payload on stdin)
│   ├── `bash_write_targets.py` - An import shim for the hooks that read paths rather than parse trees. Every reading is
│   ├── `capability_state.py` - verdict, and the INDEPENDENT (non-hook-dispatched) preactivation consumer
│   ├── `checkpoint-core.sh` - checkpoint-core.sh - Shared library for automated snapshot commits
│   ├── `claude_home.py` - Generalizes the in-repo gold-standard fail-closed self-resolution pattern
│   ├── `claude_home.sh` - claude_home.sh — shared "harness home" resolver (shell consumable).
│   ├── `close-verdict.py` - The one rule every reader of a close verdict applies: classify the close
│   ├── `close_exit.py` - the owner's --retire
│   ├── `close_rating.py` - The owner's close rating: handle() writes its row and returns the owner summary; the predicates P5's Stop gate imports.
│   ├── `codex_transcript.py` - written by scripts/steps/codex-run.py, read by the gitignore preflight as its task's provenance. ...
│   ├── `command_span.py` - rule of which transcript record is a prompt the human typed
│   ├── `commit_journal.py` - WHY THIS EXISTS
│   ├── `commit_pipeline.py` - ONE home for the two questions the commit-authorization chain could not
│   ├── `contract_runtime.py` - This module is the single shared engine consumed by every contract-aware
│   ├── `declared_absence.py` - (hooks/subagentstop-artifact-contract-enforce.py) and the orchestrator's stop
│   ├── `declared_paths.py` - hooks/pretool-tool-policy.py decides who may write a path a dispatch of the
│   ├── `deny_list.py` - The CLI applied its deny entries after the hooks, over a hook's allow, with no hook event and no ...
│   ├── `dev_loop_checks.py` - Five hooks held these checks (pretool-layer-escalation-check.sh, pretool-bisect-gate.sh,
│   ├── `dev_report_shard_patterns.py` - Single source for the per-worker / canonical dev-report filename regexes and
│   ├── `dispatch_return.py` - handback(payload) is the content, for the orchestrator (no agent_id) inside a gated command's span
│   ├── `dispatch_temp.py` - <session root>/.dispatch-tmp is this module's state and _write its one writer. Line 1 names the
│   ├── `dispatch_template.py` - A dispatch made from a base template before a merge carries no obligation block
│   ├── `do_report.py` - `docs/dev/do-report-<task_id>.json` has one producer, the /do main agent. Every
│   ├── `fact_cache.py` - watch() records, while a computation runs in this process, every file it opens, stats or lists an...
│   ├── `final_report.py` - final_report() is the SubagentHandback message of the agent's latest run, else last_assistant_mes...
│   ├── `gate_runner.py` - Claude Code starts every hook registered on an event at once, so two hooks that
│   ├── `git_clean_guard.py` - Classifies ONE Bash command for the fail-closed pre-clean guard woven into the
│   ├── `git_command_classifier.py` - classify_git_command(text) returns (invocations, residuals). Callers that
│   ├── `git_facts.py` - (How a git command line parses, which word is the subcommand, lives in lib/shell_parse.py.)"""
│   ├── `harness_state_dir.py` - state_root(): <home>/.local/state/claude-harness/<harness home's name>-<crc32 of its real path> (...
│   ├── `harness_state_dir.sh` - harness_state_dir.sh -- shell twin of hooks/lib/harness_state_dir.py.
│   ├── `harness_switch.py` - The owner's typed /harness off (commands/harness.md, scripts/harness-switch) creates
│   ├── `harness_switch.sh` - harness_switch.sh — the harness switch's one question for shell hooks and jobs: is this
│   ├── `harness_temp_state.py` - Is a resolved path harness temp state, and which temp root is it in: the one definition
│   ├── `harness_vocabulary.py` - Plain data, standard library only: a hook imports it before it reads its payload
│   ├── `hook_launch.py` - Claude Code starts every hook registered on an event as its own process, so one
│   ├── `hook_launch_fallback.py` - A dispatcher (hooks/<event>-launch.py) uses this when its own code cannot run:
│   ├── `interruption_signals.py` - Decides whether a subagent was cut off — and whether a usage limit did it — from
│   ├── `lane_ledger.py` - ``record`` (PreToolUse, hooks/pretool-lane-ledger.py, the record's one writer): before a dev suba...
│   ├── `launch_settings.py` - A launcher (hooks/<event>-launch.py, lib/hook_launch.py) is one registration that runs an
│   ├── `locations.py` - What is a device or system temp, where the harness's roots are, what lies in which directory
│   ├── `merge_grant.py` - The merge-analyst writes its grant with the Write tool at
│   ├── `obligation.py` - Rollout step S2 of the converged zero-failure design
│   ├── `overnight.py` - The state record `<main root>/.claude/overnight-state-<sid>.json` has one producer,
│   ├── `pol_degraded_removal_reference.ere` - ere file
│   ├── `policy_registry.py` - Reads the harness ``policies/tool-policy.v1.json`` (resolved via the shared
│   ├── `refusal_record.py` - The gates' advisory logs had no reader and were deleted (P1b); since then nothing could say what
│   ├── `refusal_record.sh` - refusal_record.sh -- a shell hook's report to the refusal record (hooks/lib/refusal_record.py).
│   ├── `report_provenance.py` - hooks/subagentstop-e2e-enforce.py judges the ``e2e_enforcement.status`` of the qa-report.v2
│   ├── `requirement_round.py` - the main agent asks them verbatim with one AskUserQuestion; the PostToolUse AskUserQuestion hook ...
│   ├── `returns_hold.py` - Each return of a background child wakes the orchestrator, and each wake re-reads its whole contex...
│   ├── `roster.py` - A role exists because ``agents/<role>.md`` exists and opens with YAML front
│   ├── `rule_fork.py` - A launcher (lib/hook_launch.py) holds an event's Python hooks and, once its interpreter has
│   ├── `rule_runner.py` - A merged gate (hooks/pretool-write-gate.py) and the event dispatchers
│   ├── `runtime_guard.py` - This file exists for backwards-compatibility with callers that invoke
│   ├── `schema_registry.py` - Reads schemas/registry.json once and lazily loads referenced schema files
│   ├── `score_events.py` - Score events from facts: sweep() appends the active span's events to the score log; observe() is the dispatch hook's entry.
│   ├── `score_log.py` - and views are computed on read, never stored. Rows: event {kind, ts, project, task_id, role, even...
│   ├── `score_view.py` - transcript and write nothing. ``as_of`` is the active span opener's time, so one command sees one...
│   ├── `scratch_owner.py` - hooks/session-scratch-init.sh writes <root>/<sid>/.owner = {"sid": ..., ...}. One rule reads
│   ├── `send_policy.py` - decide() is pretool-block-background-tasks.py's answer for a main-agent SendMessage;
│   ├── `sensitive_names.py` - The default is the substring rule bash-safety has always had, case-sensitive as it was: a text is...
│   ├── `shell_parse.py` - Stdlib only. Nothing here executes, expands or evaluates the text it reads, and
│   ├── `spec_path.py` - One rule, two callers: prompt-workflow.py decides a /dev, /dev-command, /redev or
│   ├── `specialist_yield.py` - Public API:
│   ├── `stop-commands.json` - JSON config: GATED_COMMANDS, CONTROL_COMMANDS, ASK_COMMANDS
│   ├── `stop_contract.py` - is a prompt the human typed (TC-4)
│   ├── `subagent.py` - is_subagent(): whether the calling agent is a subagent, the one predicate of that fact (a
│   ├── `subagent_restart.py` - Claude Code persists each subagent transcript under the parent session.  This
│   ├── `switch_prompt.py` - A delivered or scheduled prompt reaches UserPromptSubmit as if the owner had typed it, so a promp...
│   ├── `todo_canonical.py` - Shared canonical todo validation utilities
│   └── `transcript_index.py` - A conversation only grows. extend() keeps, per (conversation, kind of reading), the state a readi...
├── tests/
│   ├── fixtures/
│   │   ├── `adversarial_corpus.json` - json config
│   │   ├── `cli-agent-dispatch-hook-payloads.json` - JSON config: _doc, cli_version, recorded, runs
│   │   ├── `cli-subagent-handback-stop.json` - JSON config: _about, cli_version, subagent_stop_payload, run_start_records, text_then_handback_records
│   │   ├── `do-report-replay-completed.json` - JSON config: report_version, task_id, request_id, source, request
│   │   ├── `pol_benign_strictness_exceptions.json` - JSON config: schema, criterion, task_id, iteration, _doc
│   │   ├── `pol_installed_program_allow_set.json` - JSON config: allowing, allowing_count, criterion, probe_shape, program_set_size
│   │   ├── `pol_iteration5_qa_matrix.v1.json` - JSON config: schema, schema_descriptor, provenance_key, digests, counts
│   │   └── `protected-runtime.json` - JSON config: schema_version, protected_cmds, protected_launch_paths, protected_services, protected_hotfiles
│   ├── `_fixtures_obligation_terminal.py` - hooks/tests/test_posttool_overnight_loop_terminal_gate.py (which pins that
│   ├── `_private_ns.py` - Ways, probed in order: "root" (already root: ``unshare -m``); else "user" (``unshare -rm``, an un...
│   ├── `allowed_by_design.py` - The hook suites assert through the real hook that each of these runs (test_removal_policy_own_scr...
│   ├── `conftest.py` - mask or the subreaper setting of its process changed fails by name."""
│   ├── `pol_replay_harness.py` - ZERO-EXECUTION CONTRACT (LANE-POL AC-R02-06). Every ``command`` string in the
│   ├── `pol_sweep_generators.py` - WHY THIS FILE IS THE DELIVERABLE, NOT ITS OUTPUT (AC-R02-13). Two consecutive
│   ├── `retired_hooks.py` - A test that compares a merged rule with the hook it replaced (the write gate's overwrite rule with
│   ├── `test_agent_end_readers.py` - the /commit --bulk Stop, the close rating and ask-first read its end as G1 does
│   ├── `test_agent_tool_name_pin.py` - The CLI renamed its subagent tool from Task to Agent and still accepts "Task" as an alias. The
│   ├── `test_aggregate_check_obligation_scope.py` - from the QA dispatch's own obligation (P3 row 12)
│   ├── `test_aggregate_check_pipelines.py` - aggregator's one definition (scripts/aggregate-dev-report.py task_of_lane_report),
│   ├── `test_aggregate_check_unscoped_span.py` - (hooks/pretool-aggregate-check.py) on a QA dispatch with no obligation
│   ├── `test_allow_grant_quoted_separators.py` - The pipeline commit grant (`claude-commit-grant-*`, changelog-analyst's) reads the message through
│   ├── `test_allow_releases_anything.py` - The grant is decided in one place, where the pre-tool verdicts meet (lib/hook_launch.release_refu...
│   ├── `test_allowlist_consolidation.py` - Whether a grant releases a call is decided in one place (lib/hook_launch.release_refused, tested in
│   ├── `test_artifact_contract_enforce.py` - G2 checks the artifacts a subagent's own dispatch obligation declares at its
│   ├── `test_attribution_journal.py` - break detection, verify script verdicts, torn-tail handling, seal
│   ├── `test_ba_qa_routing_record.py` - A BA or QA handed several issues stops before any analysis and replies `multi_issue_fanout_reques...
│   ├── `test_background_dispatch.py` - 1. hooks/pretool-block-background-tasks.py lets the orchestrator dispatch any role in the
│   ├── `test_bash_execution_boundary.py` - These cover the properties the 436-case matrix cannot express on its own:
│   ├── `test_bash_execution_boundary_conditional.py` - Before this fix the walk split `[[ "$A" != "." && "$A" != ".." ]]` at its `&&`
│   ├── `test_bash_execution_boundary_dynamic_interpreter.py` - Before this fix, `python3 -c "import shutil; shutil.rmtree('$HOME/x')"` reached
│   ├── `test_bash_safety_channel_script_operand.py` - script operand spelled through the quoted CLAUDE_HOME channel as the named script file it is,
│   ├── `test_bash_safety_command_position.py` - command's own arguments (lib/shell_parse.py), not raw-text co-occurrence
│   ├── `test_bash_safety_consent_flag.py` - The flag is <state dir>/claude-orchestrator-consent-<session id>.flag. Its one writer is hooks/pr...
│   ├── `test_bash_safety_context.py` - They were written for hooks/lib/bash_context_strip.py's
│   ├── `test_bash_safety_context_rules.py` - hooks/pretool-bash-safety.sh that read the context-stripped view
│   ├── `test_bash_safety_degraded_fallback.py` - Until 2026-11-19 a command passed the degraded path only when it was provably plain: no removal r...
│   ├── `test_bash_safety_git_clean.py` - hooks/pretool-bash-safety.sh (task dev-20260719-150041-a, lane r01-a)
│   ├── `test_bash_safety_http_stop_npm_global.py` - The HTTP /stop rule (BS-02, search-15) refuses a request to a localhost port's /stop path segment...
│   ├── `test_bash_safety_kill_by_pattern.py` - pkill, killall, and kill of PIDs the same command computes from a process search (pgrep, pidof, p...
│   ├── `test_bash_safety_plain_pipelines.py` - Until 2026-11-20 one pipeline that was not a plain shape (any `if` or `for`, a variable argument,...
│   ├── `test_bash_safety_preclean_stdin.py` - An exec'd process gets its environment and argv strings through the kernel, which refuses one str...
│   ├── `test_bash_safety_rules.py` - their cases, the over-blocks fixed, the bulk-commit writer closed from Bash, and the release word...
│   ├── `test_bash_safety_sensitive_names.py` - check (`.env`, `credentials`, `secret`, `password`) over the full path of each parsed write targe...
│   ├── `test_bash_safety_session_dirs.py` - The name may stand only as a search pattern (grep, rg, git grep, git log -S/-G/--grep) or in a gi...
│   ├── `test_bash_safety_worktree_git_view.py` - judge the git invocations lib/shell_parse.py finds, not the raw text: a git subcommand named in d...
│   ├── `test_bash_views_guard.py` - the quoted CLAUDE_HOME channel spelling P2 R6 gave every command line, as it
│   ├── `test_bash_write_targets_policy.py` - Execution-semantic write-target resolution at the exact sink use site.
│   ├── `test_blackbox_integration.py` - WHAT THIS PROVES, AND WHAT IT EXPLICITLY DOES NOT
│   ├── `test_block_branch_pr_worktree.py` - The hook refuses worktree CREATION on the Bash surface, with three bypasses (in
│   ├── `test_block_branch_pr_worktree_fails_closed.py` - On an error it does not expect, a payload it cannot read or an import that fails
│   ├── `test_block_branch_pr_worktree_gh_checkout.py` - Creating a branch is allowed, so the hook lets every `gh pr checkout` through,
│   ├── `test_bulk_commit_sentinel.py` - Covers:
│   ├── `test_c_layer_protected_targets.py` - d1b244f0 made a shell `-c` layer fail closed: run-time text given to a program outside
│   ├── `test_capability_gate.py` - Every test drives the real artefacts: the library, the PreToolUse gate hook as a
│   ├── `test_carry_join_by_key.py` - rating row yields to a rating row of the same canonical task id), not by identical line: an event...
│   ├── `test_checklist_lock_read_only.py` - pretool-workflow-gate.py holds every tool but TodoWrite/TodoRead while the
│   ├── `test_checklist_record.py` - Every TodoWrite and Agent call the CLI ran is in the session transcript, so the
│   ├── `test_checkpoint_left_out.py` - In the harness home four leftover untracked files holding a listed literal made the rule refuse
│   ├── `test_checkpoint_left_out_callers.py` - The pre-clean guard (hooks/pretool-bash-safety.sh, a granted `git clean`): a snapshot that left a...
│   ├── `test_checkpoint_pii_gate.sh` - Regression tests for the checkpoint PII/credential hard-exclude + push gate
│   ├── `test_checkpoint_project_top.py` - hooks/lib/checkpoint-core.sh snapshots a project only when the project's directory is the top of
│   ├── `test_checkpoint_root_top.py` - Once a repository lay at the filesystem root by accident, and the snapshot of a session in no rep...
│   ├── `test_checkpoint_scratch_root.py` - a checkpoint snapshot fail as a whole
│   ├── `test_checkpoint_time_bound.py` - Live, a project with a few hundred tracked files and some 1,700 untracked ones (about 260 MB, non...
│   ├── `test_claude_config_guard.py` - /dev-command develops project slash commands, so its dev writes the command file the cycle asks
│   ├── `test_claude_config_guard_chain.py` - The proof (_proven_harmless) lets a Bash command the base reading refuses through when every writ...
│   ├── `test_claude_config_guard_home_spellings.py` - The guard reads the raw command text for a write into `.claude/hooks/` or `.claude/commands/`. A ...
│   ├── `test_claude_config_guard_proof.py` - The base refuses a Bash command when a cp, mv, tee or redirect word comes anywhere before a
│   ├── `test_claude_config_guard_unsettled.py` - The first OB-L31 change read each Bash command through the shared shell parser and let it through
│   ├── `test_claude_config_guard_write_targets.py` - On the base the guard refused any command where a cp, mv or tee word came anywhere before a
│   ├── `test_clean_approved_writes.py` - hooks/pretool-tool-policy.py derives it while a human-typed /clean's span is the active one: the
│   ├── `test_cli_role_own_cycle.py` - their cycle from the agent's own dispatch obligation
│   ├── `test_clock_readers.py` - time, /spec's file name): code makes each at the owner's command or at the step's own tool call, ...
│   ├── `test_close_exit.py` - owner's --force; the same texts from an agent do nothing; a cycle with files keeps the ordinary r...
│   ├── `test_close_rating.py` - hooks/posttool-close-rating.py, the rating row's one writer and the owner summary it prints (thro...
│   ├── `test_close_rating_no_tool.py` - The Stop gate cannot know a session's tools: the Stop payload carries none, and the CLI's transcr...
│   ├── `test_close_stalled_stop.py` - commands/close.md Step 0: a disposition call that exits non-zero runs once more; failing again, t...
│   ├── `test_close_verdict_round_open.py` - `CLOSE_FINDINGS: <n> items` is the never-landing return of a QA judging round
│   ├── `test_codex_skill_not_denied.py` - P5's plan (R5, A15) and P9's A13 asked for a `Skill(codex:*)` deny. P5 decided against it, by evi...
│   ├── `test_command_span.py` - The span is the records after the latest human-typed harness command outside
│   ├── `test_commit_artifact_rw_boundary.py` - WHY THIS FILE EXISTS
│   ├── `test_commit_event_pointer.py` - The privilege guard spends a grant by deleting it and, in the same step, writes one
│   ├── `test_commit_hook_bypass_deny.py` - Three rules, enforced for the main agent and for subagents alike and ahead of the
│   ├── `test_commit_journal.py` - attribution basis
│   ├── `test_commit_manifest_by_code.py` - writes it, the grant writer (scripts/write-commit-grant.py) mints from it, and the agent writes n...
│   ├── `test_commit_qa_verdict_gate.py` - What it pins (each case is a commit by the changelog-analyst the pipeline dispatched, with
│   ├── `test_config_home.py` - The configuration directory as written, unless its settings.json is a link: then the directory th...
│   ├── `test_context_v1_rules.py` - schemas/context.v1.json carries them for G2 at BA's stop (P1b rows 4 and 5)
│   ├── `test_contract_runtime_declared_vocab.py` - schema that declares them (P1b row 19 rule 7): the QA statuses the v1
│   ├── `test_contract_runtime_version_dispatch.py` - hooks/lib/contract_runtime.py (ticket 20260929-104216-a, zero-failure design
│   ├── `test_cp_checkin.py` - of ba-spec-20260427-194324.md (P1 view-trigger removal + P2 generation field)
│   ├── `test_cp_checkin_own_role_sentinel.py` - cc3077f1's rule in hooks/pretool-cp-checkin.py (_handle_dev_sentinel): a PreToolUse
│   ├── `test_cp_enforce_own_slot.py` - cp-state slot's pending checkpoints (P1c X6)
│   ├── `test_cycle_registry.py` - hooks/prompt-workflow.py mints the task id at UserPromptSubmit and arms the
│   ├── `test_declared_json_one_place.py` - The cycle counter, the closeout reader, the contract library's obligation validation and the
│   ├── `test_declared_paths_anchor.py` - (lib/declared_paths.py _target_forms; location-rules U30)
│   ├── `test_declaring_dispatch.py` - of who owes an artifact of a task, from the task's dispatch records in every
│   ├── `test_defs_programs_copy_options.py` - GNU getopt gives an optional-argument option (cp --preserve[=ATTR], --reflink[=WHEN], --context[=...
│   ├── `test_defs_programs_options.py` - - ripgrep: the options whose value is a program it runs (RG_PROGRAM_OPTS: --pre, --hostname-bin) ...
│   ├── `test_defs_programs_readers.py` - Before, the harness-switch rule kept a private list of 27 readers and refused, as a write of the
│   ├── `test_defs_programs_writers.py` - Before, a write through sort -o, touch, uniq IN OUT, sponge, gsed -i, perl -pi or gawk -i inplace
│   ├── `test_defs_tools_one_definition.py` - Each test below pins one fact the 2026-11-19 duplicate audit found written in several places
│   ├── `test_dev_loop_checks.py` - - Before a dev dispatch (PreToolUse): layer escalation and bisect; after it returns (PostToolUse):
│   ├── `test_dispatch_return.py` - state and the Stop gate's open gaps, with the gate's own text; outside one nothing; the gate is b...
│   ├── `test_dispatch_temp.py` - Every case runs the real hooks: session-scratch-init.sh writes the env file line, the dispatch gate
│   ├── `test_dispatch_template.py` - A dispatch's template is the fence of its command's file that names its
│   ├── `test_dispatch_time.py` - The orchestrator types no time: the dispatch gate (hooks/pretool-obligation-gate.py) accepts an
│   ├── `test_do_block_subagents.py` - During an active /do cycle the main agent could still dispatch dev-type
│   ├── `test_do_consent_landing.py` - hooks/prompt-workflow.py, the flag's one writer, writes it on a `/do ...` UserPromptSubmit into
│   ├── `test_do_taskid_mint.py` - Covers the root-cause fix for the do-report task-id collision (memory
│   ├── `test_doc_sync_folder_doc.py` - doc-sync's regeneration, /clean's generate-folder-index.sh and generate-folder-readme.sh,
│   ├── `test_doc_sync_hook_notices.py` - Backlog #83: a README that regen_readme() skips (no opening marker, or no closing marker)
│   ├── `test_doc_sync_index_notices.py` - Backlog #85: the INDEX regeneration path and the CLAUDE.md section patcher now report what
│   ├── `test_doc_sync_index_status.py` - Backlog #85: regen_index() returned None on every path, so nobody could tell a skipped INDEX
│   ├── `test_doc_sync_regen_all.py` - - --check exits 1 naming a drifted file and writes nothing; a plain run regenerates it through
│   ├── `test_doc_sync_regen_readme_status.py` - Backlog #83: regen_readme() returned None on every path, so nobody could tell a skipped
│   ├── `test_doc_sync_regions.py` - Backlog #85: four unrelated marker predicates (README first occurrence, INDEX substring
│   ├── `test_doc_sync_update_only.py` - A Write in a product repository leaves no CLAUDE.md, INDEX.md or README.md behind that was
│   ├── `test_dual_runtime_lifecycle_e2e.py` - Real-entrypoint regressions for single-owner ordinary dev lifecycle.
│   ├── `test_e2e_enforce.py` - is judged on
│   ├── `test_env_configured_defaults.py` - such values come only through the environment (normally the untracked settings
│   ├── `test_eval_ref_mutation.py` - `eval` joins its arguments and runs them as a command line, so
│   ├── `test_extract.py` - Unit tests for hooks/doc_sync/extract.py — covers all 4 defects + known-file cases.
│   ├── `test_fail_closed_drift.py` - WHY THIS FILE EXISTS
│   ├── `test_find_action_write_targets.py` - The shared parser's table of find actions held the four that run a program; `-fprint`, `-fprint0`,
│   ├── `test_g2_file_lists.py` - files Claude Code recorded the dev writing (hooks/subagentstop-artifact-
│   ├── `test_g2_file_lists_dispatch_start.py` - declared: the entries its report already held when the dispatch began (an earlier round's files, ...
│   ├── `test_g2_file_lists_recorded.py` - in live use: a dev dispatched to repair an older cycle's bookkeeping file (its qa-report, its spe...
│   ├── `test_g2_harness_syntax.py` - artifact-contract-enforce.py, _harness_syntax) parses every file of the
│   ├── `test_g2_spec_views.py` - subagent's stop by `spec-verify.py --strict` on the views its dispatch declares
│   ├── `test_generated_tests_policy.py` - tests/generated/ (outside the pinned directories) and the tree stays out of
│   ├── `test_git_clean_guard_argument_data.py` - read grep / rg / echo pattern text and heredoc text as a `git clean`
│   ├── `test_git_cmd_cross_consistency.py` - Verifies that GIT_COMMAND_RE (hooks/pretool-git-privilege-guard.py) and
│   ├── `test_git_dynamic_directory.py` - `"$VIRTUAL_ENV/bin/pip" show pytest` runs pip wherever the variable points:
│   ├── `test_git_facts_one_definition.py` - Each class is one fact. Before these merges each hook carried its own copy, the copies differed,
│   ├── `test_git_guard_inline_python.py` - Python given on standard input (a here-document or a here-string) was not read at all, so
│   ├── `test_git_guard_written_text_is_data.py` - A live call wrote a Markdown report with `cat > <absolute path> <<'EOF'`; the report quoted git c...
│   ├── `test_git_hidden_code.py` - The classifier reads shell text, so `python3 -c 'subprocess.run(["git","push"])'`
│   ├── `test_git_prefix_enumeration.py` - THE DEFECT
│   ├── `test_git_residual_override.py` - Background
│   ├── `test_git_residual_shell_string_message.py` - `for d in */; do bash -c "cd $d && git status"; done` stays refused: the outer
│   ├── `test_git_shell_c_strings.py` - `bash -c "git commit -m y"` runs git, but the shell segment's command token is
│   ├── `test_git_text_owners.py` - Four readings, each with the inputs that must still be refused:
│   ├── `test_git_view_reads_as_shell.py` - Each case is a decision that changed when the classifier moved from a
│   ├── `test_git_word_unquoted.py` - as git receives them, quotes and backslashes removed, before any rule judges them
│   ├── `test_gitignore_preflight_close_contract.py` - The gate previously harvested any docs/dev/dev-report-*.json cited anywhere in an
│   ├── `test_gitignore_preflight_reads.py` - dispatch ships them (E8, E9 in hooks/pretool-gitignore-preflight.py's header)
│   ├── `test_gitignore_preflight_speed.py` - Dev dispatches ended the PreToolUse launcher with a RuleOverrun traceback after 60 s: each
│   ├── `test_gitignore_preflight_write_capability.py` - pretool-gitignore-preflight.py scopes its refusal by the dispatched agent's
│   ├── `test_grant_binding.py` - hooks/pretool-tool-policy.py, beside the derived write permission and for every caller alike:
│   ├── `test_grant_judges_the_thing_not_its_place.py` - The same thing put at two places gets the same verdict:
│   ├── `test_grep_backtrack_guard.py` - Freeze safe grep shapes and the catastrophic embedded-engine control.
│   ├── `test_grep_backtrack_probe_start.py` - The probe runs inside a transient systemd scope. A launch delay of systemd-run
│   ├── `test_hard_ban_noexec.py` - `bash -n`, `sh -n`, `bash -o noexec`, `-n` inside a short-option cluster) and a unary file test (...
│   ├── `test_harness_temp_state.py` - Each inventoried temp location classifies, symlink-safely, under every root spelling
│   ├── `test_hook_launch.py` - - settings.json registers at most one Python process per event (the CI check of row L7), and a
│   ├── `test_hook_output_reaches_model.py` - The CLI (code.claude.com/docs/en/hooks): plain stdout reaches the model on SessionStart and
│   ├── `test_inflight_push_route.py` - COMPATIBILITY TESTS, kept only as long as hooks/pretool-tool-policy.py's _note_inflight_token_rou...
│   ├── `test_lane_blockers_at_stop.py` - - a non-empty list holds the stop once, with the list shown;
│   ├── `test_lane_ledger.py` - report its stop completes. Throwaway repositories and state directories only."""
│   ├── `test_laneb_stop_coordinator.py` - LANE-B serialized Stop coordinator.
│   ├── `test_locations_relocation.py` - Each location decision is the same wherever the project and the harness home are, by every spelli...
│   ├── `test_merge_grant_write_check.py` - Experiment E11: the privilege guard's merge-grant check sat behind
│   ├── `test_merge_verdict_enforced.py` - commands/merge.md Step 3's prose alone
│   ├── `test_misread_refusals.py` - Each group holds the shapes of refusals recorded in three days of sessions (paths, names and PIDs...
│   ├── `test_monitor_command.py` - On CLI 2.1.325 (measured) a Monitor call reaches matcher-less hooks as tool_name "Monitor" with
│   ├── `test_no_automatic_move.py` - one explicit step of the install tooling (scripts/install/carry_state.py), which only the configu...
│   ├── `test_now_unreferenced_p5_p9.py` - - posttool-subagent-track.py's bookmark marker. P5 moved Gate 4 to the transcript, so
│   ├── `test_obligation.py` - Covers the four implementation ACs of ticket-20260929-104216-b:
│   ├── `test_obligation_gate.py` - G1 is the first of five enforcement doors (spec-20260930-092323) that move
│   ├── `test_obligation_gate_returns.py` - back, not only its own Agent call's result
│   ├── `test_obligation_templates.py` - Two template forms exist: literal ``<obligation v="1">`` blocks, and the
│   ├── `test_one_process_gates.py` - - The runner keeps each rule's decision: a rule runs as its own hook would run alone,
│   ├── `test_orchestrator_gate_in_flight.py` - P9 reworded the gate's refusals (the Bash limit's and the non-whitelisted limit's first line, the
│   ├── `test_orchestrator_gate_newer_tools.py` - hooks/pretool-orchestrator-gate.py allowed each of these once per turn, as any tool outside its
│   ├── `test_orchestrator_gate_overnight_budget.py` - hooks/pretool-orchestrator-gate.py allows the main agent one call per non-whitelisted tool name per
│   ├── `test_orchestrator_gate_pins.py` - Pins the gate's always-allowed set, its Bash cap and its permanent plan-mode block, where no test...
│   ├── `test_orchestrator_gate_plan_mode.py` - hooks/pretool-orchestrator-gate.py listed ExitPlanMode in PERMANENTLY_BLOCKED, so when the user
│   ├── `test_orchestrator_gate_read_budget.py` - hooks/pretool-orchestrator-gate.py allowed the main agent one call per non-whitelisted tool name ...
│   ├── `test_orchestrator_gate_read_only_bash.py` - hooks/pretool-orchestrator-gate.py counted every main-agent Bash call toward its cap of 5, so a t...
│   ├── `test_orchestrator_gate_refused_refund.py` - hooks/pretool-orchestrator-gate.py counts a call at PreToolUse, before the other hooks have decided
│   ├── `test_orchestrator_gate_scratch_write.py` - hooks/pretool-orchestrator-gate.py allows the main agent one call per non-whitelisted tool name per
│   ├── `test_overnight_a12_timelock_cases.py` - A12 (prompts/P5.md acceptance 12; prompts/short/P5.md A12) says, of the overnight time-lock:
│   ├── `test_overnight_contract_span_scope.py` - pretool-subagent-enforce.py reads the in-progress step label of the active
│   ├── `test_overnight_cycle_contract.py` - - No seed file: the exploration (steps 2-4) passes the dispatch hook in cycles
│   ├── `test_overnight_git_config_write_guard.py` - The keystone's core.hooksPath lives in the repository's git config. bubblewrap's
│   ├── `test_overnight_gitenv_failclosed.py` - Two halves of one fail-open, scoped together because closing either alone leaves
│   ├── `test_overnight_guard_bash_parser.py` - Each decision that changed when the guard's Bash path moved onto the parser is pinned here, with
│   ├── `test_overnight_inplace_bubblewrap.py` - Replayed in a bwrap-less in-place toy session, every removal of the git
│   ├── `test_overnight_keystone_hook_dir.py` - In both isolation modes neither a `chmod -x` of `<common>/keystone-hooks/reference-transaction`
│   ├── `test_overnight_notebook_edit.py` - The guard named Write, Edit and MultiEdit at five places and read `file_path`; its write-gate row
│   ├── `test_overnight_one_state_reader.py` - cycle contract's one writer (P1b row 13, E13)
│   ├── `test_overnight_operand_scan_channel.py` - The commands run harness scripts as `bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/x.sh"`. For an
│   ├── `test_overnight_qa_sentinel_bind.py` - P1b E7 removed the one RW exception the boundary had under main's
│   ├── `test_overnight_question_deny.py` - hooks/pretool-overnight-hook-guard.py denies AskUserQuestion to every caller of
│   ├── `test_overnight_row13_consumers.py` - - The PM test plan, triage and retro reports and the specialists' reports are
│   ├── `test_overnight_state_file_write_guard.py` - overnight-state write-protection (ticket 20261001-161041-r10, AC4/AC5/AC6)
│   ├── `test_overnight_trace_yield.py` - (P1b row 18)
│   ├── `test_overnight_wake.py` - The wake is one recurring CronCreate of lib/overnight.py's WAKE_PROMPT, scheduled at Step 0 and d...
│   ├── `test_overnight_window.py` - window_open, closeout_gaps, stop_contract.timelock_released and the /stop helper
│   ├── `test_overnight_worktree_config_file.py` - With `extensions.worktreeConfig` on, git reads `<gitdir>/config.worktree` after the shared config...
│   ├── `test_overnight_worktree_no_bwrap.py` - Measured on d64fa96 with no bubblewrap: the guard refused /dev-overnight's Step 1 in
│   ├── `test_overwrite_guard.py` - The overwrite guard was never registered and was deleted with its route
│   ├── `test_own_scratch_symlink.py` - A write, removal or commit inside the caller's own scratch directory passes with fewer checks
│   ├── `test_pipeline_cycle_stamp.py` - Step 6's builder call, run as the text writes it, passes `-` for the stamp: scripts/build-pipelin...
│   ├── `test_place_reads_follow_the_thing.py` - F8  The capability doctor never takes the user's home, the harness home or / as the session's pro...
│   ├── `test_pol_generative_sweeps.py` - AC-R02-10 .. AC-R02-16 (revision 2). Every deny-side population here is
│   ├── `test_posttool_checkpoint_refusal.py` - Drives hooks/posttool-git-checkpoint.sh as settings.json registers it (PostToolUse on
│   ├── `test_posttool_overnight_loop_terminal_gate.py` - re-checks any artifact (P1b row 3: the G4 terminal-lane block is gone)
│   ├── `test_pretool_bulk_commit_detector.py` - of hooks/pretool-launch.py, and of the Monitor rule's Bash list, went), and the file stays for a ...
│   ├── `test_privilege_guard_checkpoint_fetch.py` - The auto-commit mechanism snapshots work to `refs/checkpoints/<branch>` (see
│   ├── `test_privilege_guard_commit_file_operand.py` - The `-F` operand is taken from the shell-tokenised commit invocation and unquoted,
│   ├── `test_privilege_guard_fails_closed.py` - When a name the guard imports from the classifier is missing, the guard raises at
│   ├── `test_privilege_guard_gp08.py` - A push that forces, deletes or mirrors a ref is refused for every agent with the
│   ├── `test_privilege_guard_one_reader.py` - An auto-bulk commit is one whose own message carries the `auto-bulk:` subject: an
│   ├── `test_privilege_guard_own_scratch_commit.py` - The privilege guard refused every agent `git commit` without a /commit grant, also one in a repos...
│   ├── `test_privilege_guard_read_only_forms.py` - Its rules judge an invocation by its subcommand name, so help (`git push --help`,
│   ├── `test_privilege_guard_refusal_routes.py` - P9-5 (owner ruling D19): no step may send the owner to his own shell. The commit refusal
│   ├── `test_product_repo_session_bookmark_hygiene.py` - The real SessionStart exclude step runs first, then the real UserPromptSubmit start
│   ├── `test_program_dir_spelling.py` - The session-dirs rule and the bulk-commit-sentinel rule read a command word in a plain program di...
│   ├── `test_prompt_workflow_replay_window.py` - envelope only while its replay record is younger than 60 s, judged by the
│   ├── `test_prompt_workflow_session_roots.py` - dev.md's and dev-command.md's start-function fallback runs when the command start's output is gone:
│   ├── `test_prompt_workflow_subagent_roots.py` - No UserPromptSubmit output reaches a subagent, so an agent text's harness line kept the
│   ├── `test_prompt_workflow_turn_state.py` - hooks/prompt-workflow.py ``_clear_turn_state`` runs at every UserPromptSubmit: it removes
│   ├── `test_push_gate_ancestor_cross_session.sh` - Regression test for hooks/push.sh's push-gate token scan (task 20260924-031253):
│   ├── `test_push_no_upstream_guard.sh` - Regression test for hooks/push.sh R22 (line ~375): HAS_UPSTREAM must be
│   ├── `test_push_sentinel_abort.sh` - Unit test for AC1 V5: hooks/push.sh self-aborts before any real git push
│   ├── `test_push_typed_remote.py` - execute-push.py hands push.sh the resolved remote as its argument. The ahead count is taken against
│   ├── `test_qa_report_writes.py` - qa writes report and evidence files under the project's reports/ and tests/reports/ only
│   ├── `test_read_size_guard_offset.py` - the number of lines it actually returns (OB-L43)
│   ├── `test_reader_memos.py` - A hook that reads every dispatch of a long session asks for the same roster and
│   ├── `test_refusal_record.py` - - One refused call, stop or prompt is one line holding every field of the record, each bounded;
│   ├── `test_refusal_record_every_rule_text.py` - - Two live cases: a Bash call that both the removal policy (lib/bash_safety_rules.py, the text th...
│   ├── `test_refused_calls.py` - A PreToolUse hook's refusal reaches two records: the refusal record (lib/refusal_record.py), writ...
│   ├── `test_removal_policy_container_entrypoint.py` - `--entrypoint` (a separate word or `=`-joined, on `run` and `create`) names the program the conta...
│   ├── `test_removal_policy_container_options.py` - Four container runs were refused on one day as an unresolved removal (`unknown_option:--dns`, `--...
│   ├── `test_removal_policy_o2_o4.py` - Each command below was denied as UNRESOLVED because the census or the lexer
│   ├── `test_removal_policy_own_scratch.py` - The owner, 2026-11-19: one's own temp folder may be deleted. Until then every removal the analyze...
│   ├── `test_removal_policy_parsed_rule.py` - "Only a removal program in a position where it would be executed counts, and removal calls in Pyt...
│   ├── `test_removal_policy_unproven_rule.py` - The rule (owner, 2026-11-19): when the guard cannot prove a command safe, it refuses if a removal...
│   ├── `test_report_projection_contract.py` - Focused contract tests for the deterministic QA v1 report projection and the report gate.
│   ├── `test_report_provenance_gate.py` - The orchestrator could forge ``docs/dev/qa-report-*.json`` (an ``e2e_enforcement.status`` of
│   ├── `test_report_provenance_reads.py` - the fifth verifier's findings, through the registered PreToolUse launcher in a throwaway project,
│   ├── `test_report_provenance_replay.py` - the hook's own code path by hand, and a replayed ledger
│   ├── `test_report_provenance_tamper.py` - hooks/tests/test_report_provenance_gate.py proves the measured writer refuses the main agent's
│   ├── `test_report_provenance_witness.py` - hooks/lib/report_provenance.py once took a background QA launch from an ``async_launched`` result
│   ├── `test_requirement_round.py` - hook that calls it
│   ├── `test_residual_false_positives.py` - Context (task 20260903-residual-fp). `classify_git_command()` returns a
│   ├── `test_returns_hold.py` - orchestrator come back as one batch. Notices are the CLI's recorded shapes (tests/cli_shapes; the...
│   ├── `test_role_drafts_session_root.py` - policies/tool-policy.v1.json (policy_version 10) gives each of the 21 roles that keep drafts the ...
│   ├── `test_role_from_cli.py` - The role is the payload's agent_type when it carries an agent_id, else the agentType of
│   ├── `test_root_no_top.py` - hooks/tests/test_checkpoint_root_top.py closed the checkpoint; this closes the writers that resol...
│   ├── `test_root_no_top_places.py` - the filesystem root is no top, so each decides below a repository at the root as in a directory i...
│   ├── `test_round_step_calls.py` - ROUND_CALLS, shared by /dev-command and, through dev.py, /redev)
│   ├── `test_runcode_watchdog_aliases.py` - Direct lifecycle parity tests for both browser run-code provider names.
│   ├── `test_runtime_guard.py` - Two layers:
│   ├── `test_runtime_guard_drifted_config.py` - A schema-1 file that lacks some REQUIRED_KEYS lists (written before a key existed, or
│   ├── `test_score_view.py` - hooks/lib/score_log.py renders the views (dispatch view, main line) and hooks/lib/score_view.py r...
│   ├── `test_scratch_lifecycle.py` - Covers:
│   ├── `test_scratch_owner_one_reader.py` - directory one root rule (hooks/lib/scratch_owner.py, hooks/lib/locations.py)
│   ├── `test_session_git_init_broad_root.py` - or a directory above it (location-rules U32)
│   ├── `test_session_gitignore_propagate.py` - product repo, and the two per-session records it keeps directly in .claude/ (the workflow bookmark
│   ├── `test_session_root_lifetimes.py` - hooks/pretool-tool-policy.py, hooks/lib/harness_temp_state.py)
│   ├── `test_shared_lists_agree.py` - - Finding 15, devices no write changes: the overnight boundary knew /dev/null, tool-policy's rows
│   ├── `test_shell_parse.py` - Unit tests of hooks/lib/shell_parse.py: one class per node type and view.
│   ├── `test_skill_deny_coverage.py` - `disable-model-invocation: true` blocks the SlashCommand route only; the `Skill(<stem>)` entry of...
│   ├── `test_space_pressure.py` - hooks/userprompt-tmpfs-pressure.sh (and hooks/session-tmpfs-banner.sh, which runs it at SessionSt...
│   ├── `test_span_lazy_reader.py` - what decides (P1b FX4: FX1's CS-1..3 and OB-2)
│   ├── `test_spec_flag_prose.py` - in a /dev, /redev, /dev-command or /dev-overnight prompt as the --spec flag, and
│   ├── `test_spec_path.py` - and prompt-workflow.py's one decision of a run's spec built on it, replayed at
│   ├── `test_spec_path_one_reader.py` - transcript reader the Stop gate decides on, and finds the spec the old parser of its own
│   ├── `test_spec_root_anchoring.py` - hooks/pretool-bash-views-guard.py refused a Bash redirect into any `*.lock.json` anywhere
│   ├── `test_spec_root_symlink_dotdot.py` - directory destination and `touch` (OB-L37 rework)
│   ├── `test_spec_window_abandoned.py` - pretool-spec-block-foreground-agent.py refuses a foreground dispatch while a
│   ├── `test_specialist_report_repair.py` - /dev-overnight Step 3 (commands/dev-overnight.md, the specialist template) dispatches architect,
│   ├── `test_start_launchers.py` - and SubagentStart (P2-3), as rules of the one Python registration each event has (P12-L7, lib/hoo...
│   ├── `test_state_dir_path_rule.py` - Each test pairs a state file's writer with its reader: with CLAUDE_STATE_DIR pointing
│   ├── `test_state_root_on_disk.py` - The incident behind it: the default control-state dir was /tmp, a memory-backed volume; with /tmp...
│   ├── `test_stop_block_bound.py` - first, the GAP lines counted by (problem, lane) with samples, and how many lines were left out; n...
│   ├── `test_stop_bound.py` - 1. An --auto run's task list is fixed when the owner's command arrives (hooks/userprompt-auto-tar...
│   ├── `test_stop_checkpoint_noop_no_ref.py` - Drives the registered Stop hook, hooks/stop-launch.py, and the coordinator with its four default
│   ├── `test_stop_checkpoint_refusal.py` - Drives the registered Stop hook, hooks/stop-launch.py, and the coordinator with its four default
│   ├── `test_stop_cold.py` - keeps does not depend on its own refusals
│   ├── `test_stop_command_gate.py` - The gate calls P3's disposition, P2's overnight locator and window, and P4's
│   ├── `test_stop_contract.py` - Pins the command tuples, the human-typed prompt rule (is_human_prompt), the
│   ├── `test_stop_incremental.py` - 1. A grown conversation (a continuation) gives the records a whole read gives, whatever was added...
│   ├── `test_stop_kept_answers.py` - 1. What a computation asked of the saved conversations (the dispatch records of a task, obligatio...
│   ├── `test_stop_launch.py` - The launcher runs the Stop coordinator and relays it; when the coordinator cannot decide it
│   ├── `test_stop_md_userintent_wrapper.py` - commands/stop.md runs the release wrapper through the printed harness root. hooks/pretool-wrapper-
│   ├── `test_stop_scan_no_chain_load.py` - The Stop gate's one scan is opened on the chain's copy of obligation without loading the chain script.
│   ├── `test_stop_span_kept.py` - 1. Inside a scan that keeps its readings, what the reader of command spans returns (the open comm...
│   ├── `test_subagent_handback_report.py` - In auto mode a subagent delivers its final report as a SubagentHandback call: the
│   ├── `test_subagent_time_limit.py` - The clock is set by each test: the subagent's own transcript, as the CLI keeps it beside the
│   ├── `test_subagentstop_codex_enforce.py` - The codex ledger's one deciding read blocks a stopping subagent whose session
│   ├── `test_subagentstop_cp_enforce.py` - Armed as shipped (settings.json's env sets CP_ENFORCE_MODE=block), the hook blocks
│   ├── `test_test_writer_manifest_skeleton.py` - (agents/test-writer.md, agents/dev.md "Generated tests"). schemas/test-writer-manifest.v1.json
│   ├── `test_todo_after_completion.py` - pretool-todo-validate.py held every TodoWrite of a span to the canonical list, so once a command's
│   ├── `test_todo_script_fork.py` - lib.todo_canonical.run_todo_script runs a harness todo script in a fork of the
│   ├── `test_todo_validate_after_restart.py` - A dev subagent cut before its Agent call came back (no tool_result, or the CLI's error result aft...
│   ├── `test_todo_validate_in_flight.py` - The owner cannot stop his sessions: one that took up origin/master's /close before train 2 landed
│   ├── `test_todowrite_pin.py` - settings.json's env carries CLAUDE_CODE_ENABLE_TASKS=false and CLAUDE_CODE_ENABLE_TODO_TOOLS=1; the
│   ├── `test_tool_policy_browser_tools.py` - Recorded: a qa subagent's mcp__paseo__browser_new_tab, refused with "not in allowed_tools", so th...
│   ├── `test_tool_policy_c_layer_writes.py` - hooks/pretool-tool-policy.py judges a Bash command's write targets (the protected stage for every
│   ├── `test_tool_policy_contracts.py` - LANE-POL least-privilege role-policy regression matrix.
│   ├── `test_tool_policy_declared_write_means.py` - The recorded case: a /dev fan-out lane's dev, fixing one contract cell, also had to change the sa...
│   ├── `test_tool_policy_derived_permission.py` - hooks/pretool-tool-policy.py runs it before the role rows, for every caller, the main agent
│   ├── `test_tool_policy_dispatch_writes.py` - hooks/pretool-tool-policy.py's _check_dispatch_writes: for each file artifact (a kind whose fields
│   ├── `test_tool_policy_docs_and_web.py` - policies/tool-policy.v1.json is default-deny per role: lib/policy_registry._check_tool_lists refu...
│   ├── `test_tool_policy_hooks_only_state.py` - hooks/pretool-tool-policy.py `_protected` reads the inventory: an entry marked hooks_only, and a ...
│   ├── `test_tool_policy_own_scratch.py` - hooks/pretool-tool-policy.py refuses every role a write under /tmp or /var/tmp (the shipped
│   ├── `test_tool_policy_own_scratch_variable.py` - hooks/pretool-tool-policy.py reads a Bash command's write targets statically. A target that expan...
│   ├── `test_tool_policy_protected_paths.py` - hooks/pretool-tool-policy.py refuses, before every other rule and for the main agent and every
│   ├── `test_tool_policy_readonly_bookkeeping.py` - policies/tool-policy.v1.json is default-deny per role: lib/policy_registry._check_tool_lists refu...
│   ├── `test_tool_policy_refusal_means.py` - Two refusals that named none: the watcher tool (Monitor), which no role's list holds, refused wit...
│   ├── `test_tool_policy_report_forgery.py` - hooks/subagentstop-e2e-enforce.py (inside hooks/subagentstop-producer-gate.py) judges the
│   ├── `test_transcript_request_copies.py` - it as without them (C3)
│   ├── `test_unit_anchor.py` - Imports the anchor sibling module DIRECTLY (not via the _core facade) and
│   ├── `test_unit_config.py` - Imports the config sibling module DIRECTLY (not via the _core facade) and
│   ├── `test_unit_constants.py` - Imports the constants sibling module DIRECTLY (not via the _core facade) and
│   ├── `test_unit_find_cmds.py` - Imports the find_cmds sibling module DIRECTLY (not via the _core facade) and
│   ├── `test_unit_git_cmds.py` - Imports the git_cmds sibling module DIRECTLY (not via the _core facade) and
│   ├── `test_unit_pathmatch.py` - Imports the pathmatch sibling module DIRECTLY (not via the _core facade) and
│   ├── `test_unit_shell_lex.py` - The guard splits a command into pipeline groups of simple commands, tokenizes each
│   ├── `test_unproven_presnapshot.py` - The owner's rules: a command the removal policy cannot prove safe runs and is recorded (2026-11-1...
│   ├── `test_unwritable_state_fails_loud.py` - Behaviours pinned (each hook runs as a subprocess with its own HOME, project and state dir):
│   ├── `test_userprompt_bulk_commit_capability.py` - These assertions (AC-FRESH-F-14) came from the tests of an unreachable script
│   ├── `test_userprompt_doc_sync_relay.py` - Backlog #83: the UserPromptSubmit hook resyncs a directory by running
│   ├── `test_userprompt_usage_snapshot.py` - Covers the three cache states the hook must handle (cache hit, cache expired
│   ├── `test_views_guard_checker_exemption.py` - names it (hardcode audit 2026-11-19, finding 12)
│   ├── `test_workflow_allow_grant.py` - pretool-block-background-tasks.py refuses every Workflow call of the main agent. The owner's
│   ├── `test_workflow_bookmark_writer.py` - <project>/.claude/workflow-<sid>.json is written by prompt-workflow.py alone (a
│   ├── `test_worktree_guard.py` - agent worktrees
│   ├── `test_wrapper_userintent_computed_parts.py` - hooks/pretool-wrapper-userintent.py:
│   ├── `test_wrapper_userintent_execution.py` - hooks/pretool-wrapper-userintent.py refuses a Bash call that runs the harness home's
│   ├── `test_wrapper_userintent_hidden_runs.py` - hooks/pretool-wrapper-userintent.py identifies the harness home's wrapper by path, by
│   ├── `test_wrapper_userintent_named_loops.py` - hooks/pretool-wrapper-userintent.py protects one thing: the /stop release wrapper (the files
│   ├── `test_wrapper_userintent_operand_proofs.py` - hooks/pretool-wrapper-userintent.py:
│   ├── `test_wrapper_userintent_proof.py` - hooks/pretool-wrapper-userintent.py keeps the previous text rule as its fallback: a
│   ├── `test_wrapper_userintent_runtime_targets.py` - hooks/pretool-wrapper-userintent.py treats as a run of the harness home's wrapper:
│   ├── `test_wrapper_userintent_unread_names.py` - Two recorded refusals: a for loop whose script name is computed from the loop variable, every value
│   ├── `test_write_gate.py` - - The gate sees what the guards saw: each rule's tool set is its guard's registered matcher
│   ├── `test_write_gate_overwrite_exempt.py` - Each case runs the rule (lib/write_gate/overwrite.py) as a process on an architect subagent's Write
│   ├── `test_write_gate_overwrite_parity.py` - The write gate runs the Python form. The shell hook is an exit-0 stub since the gate's registration
│   ├── `test_write_guard_consent_process.py` - The file is an exit-0 stub since the write gate's registration landed (D15); its checks are the g...
│   ├── `test_write_push_gate_token.py` - changelog-analyst (under /commit) and the cleaner (under /clean) both call it after
│   └── `write_gate_settings.py` - From the P12 base (retired_hooks.BASE) to the tracked settings.json:
├── `auto-commit.sh` - auto-commit.sh - Stop hook: snapshot on conversation end
├── `capability-canary.py` - Registered once per relied-upon lifecycle event, each registration carrying its
├── `check-todo-md-sync.py` - check-todo-md-sync.py — Session-start drift detector for todo scripts
├── `checkpoint.sh` - checkpoint.sh - Manual /checkpoint command
├── `fswatch-manager.sh` - fswatch-manager.sh - Manage git-fswatch instances
├── `git-fswatch.sh` - git-fswatch.sh - Comprehensive Git file watcher using fswatch
├── `git-fswatch@.service` - service file
├── `merge.sh` - merge.sh - wrapper for /merge slash command
├── `permissionrequest-answer.py` - Its rules are stated once, in docs/how-it-works.md ("Permission prompts") and ledger row H-101; d...
├── `permissionrequest-launch.py` - PermissionRequest: answer every permission request by rule (hooks/permissionrequest-answer.py).
├── `posttool-allowlist-consume.py` - PostToolUse Hook (and PostToolUseFailure, Bash): the commit-event finalization
├── `posttool-attribution-post.py` - Pairs with pretool-attribution-pre.py via (session_id, tool_use_id). Purely
├── `posttool-close-rating.py` - A question goes by its source prefix to one handler, an Agent call to the observer; no logic here
├── `posttool-codex-skill-ledger.py` - Fires on every PostToolUse and PostToolUseFailure for the Skill tool. When tool_input.skill == "c...
├── `posttool-command-frontmatter-validate.py` - PostToolUse Hook: Validate .claude/commands/*.md frontmatter structure
├── `posttool-dispatch-record.py` - The rules run in this order, each as its own hook would run alone
├── `posttool-doc-sync.py` - PostToolUse Hook: keep the marked INDEX.md, README.md and CLAUDE.md sections in sync
├── `posttool-failure-launch.py` - PostToolUseFailure: record consumed Bash grants and attempted Codex Skill calls.
├── `posttool-git-checkpoint.sh` - posttool-git-checkpoint.sh - PostToolUse checkpoint trigger
├── `posttool-git-warn.sh` - posttool-git-warn.sh - PostToolUse (Bash): after a git commit, tell the model which files it left untracked.
├── `posttool-launch.py` - Every Python hook registered on PostToolUse runs here, each as `python3 <file>` would have run it
├── `posttool-orchestrator-ran.py` - hooks/pretool-orchestrator-gate.py counts a main-agent call at PreToolUse, before the other hooks'
├── `posttool-overnight-file-check.py` - PostToolUse:Agent Hook — Contract-driven overnight file check (G3)
├── `posttool-overnight-loop.py` - PostToolUse:TodoWrite Hook: Overnight Loop Detection
├── `posttool-overnight-trace.py` - Records the yield of a specialist's report in an overnight cycle
├── `posttool-restart-sendmessage.py` - A validated /restart send is recorded as dispatched in the restart state, as before; any other
├── `posttool-runcode-watchdog.py` - PostToolUse Hook: Cancel timeout watchdog after browser_run_code completes
├── `posttool-subagent-track.py` - PostToolUse:Agent Hook: the cycle contract's one writer (/dev-overnight)
├── `posttool-todo-tracker.py` - PostToolUse Hook: Output checklist progress after every TodoWrite call
├── `pre-commit-check.sh` - pre-commit-check.sh - Detect untracked files before commit
├── `pretool-aggregate-check.py` - existence before allowing the orchestrator to dispatch the QA subagent in
├── `pretool-attribution-pre.py` - Phase 0 of the write-time attribution journal (see hooks/lib/attribution_journal.py)
├── `pretool-bash-safety.sh` - PreToolUse safety hook for Bash: the rules live in lib/bash_safety_rules.py, run in one interpreter per call.
├── `pretool-bash-views-guard.py` - Parallels pretool-bash-safety.sh but focuses on views/cp-state write bypass
├── `pretool-bisect-gate.sh` - STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
├── `pretool-block-background-tasks.py` - PreToolUse hook: block background execution on Bash/SendMessage/Workflow for the
├── `pretool-block-branch-pr-worktree.py` - Refused: every `git worktree add` the command runs, in command position, inside
├── `pretool-block-enterworktree.sh` - PreToolUse hook: Block EnterWorktree tool
├── `pretool-bulk-commit-detector.py` - It warned through additionalContext when a plain commit staged files across three or more of
├── `pretool-capability-gate.py` - Blocks (exit 2) any protected-workflow activation route unless the host-capability
├── `pretool-claude-config-guard.py` - PreToolUse Hook: Claude config (.claude/hooks + .claude/commands) protection
├── `pretool-commit-dispatch-attest.py` - Writes `<state-dir>/claude-commit-dispatch-<sid>-<nonce>.json` when, and only
├── `pretool-cp-checkin.py` - cp-state file read (the write is scripts/spec-check.py's `register`)
├── `pretool-cp-state-write-guard.py` - Only a direct Write/Edit/MultiEdit/NotebookEdit of a cp-state path exits 2: a
├── `pretool-deny-list.py` - The entries are policies/cli-deny.v1.json, matched as the CLI matched them (lib/deny_list.py). A ...
├── `pretool-dispatch-gate.py` - The rules run in this order, each as its own hook would run alone (its switch, its
├── `pretool-do-block-subagents.py` - PreToolUse hook: block Agent/Task dispatch from the MAIN agent while a /do
├── `pretool-git-privilege-guard.py` - PreToolUse Hook: Agent git-privilege guard
├── `pretool-gitignore-preflight.py` - pretool-gitignore-preflight.py — PreToolUse hook (matcher: Agent)
├── `pretool-grep-backtrack-guard.py` - Why
├── `pretool-harness-switch-guard.py` - SlashCommand): only the owner switches the harness
├── `pretool-harness-switch-prompt.py` - Every tool but Bash, the file-writing tools, Skill and SlashCommand (hooks/pretool-harness-switch...
├── `pretool-lane-ledger.py` - Observational: never blocks, always exits 0; a failure records nothing and the lane's stop finds ...
├── `pretool-launch.py` - Every Python hook registered on PreToolUse runs here, each as `python3 <file>` would have run it
├── `pretool-layer-escalation-check.sh` - STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
├── `pretool-layer-match-gate.sh` - STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
├── `pretool-merge-verdict.py` - A Bash call that runs this harness's hooks/merge.sh exits 2 unless it is /merge Step 5's call as
├── `pretool-monitor-command.py` - Monitor runs an arbitrary shell command in the background. On CLI 2.1.325 the CLI delivers that
├── `pretool-obligation-gate.py` - WHY THIS HOOK EXISTS:
├── `pretool-orchestrator-gate.py` - PreToolUse Hook: Orchestrator Gate (Unified)
├── `pretool-orchestrator-prompt-purity.py` - PreToolUse hook: Orchestrator Prompt Purity
├── `pretool-overnight-hook-guard.py` - PreToolUse Hook: Overnight session file modification guard
├── `pretool-quality-gate.py` - PreToolUse Hook: Quality gate for Write/Edit operations (advisory)
├── `pretool-read-size-guard.py` - PreToolUse Hook: Read Size Guard
├── `pretool-runcode-watchdog.py` - PreToolUse Hook: Start timeout watchdog for browser_run_code
├── `pretool-spec-block-foreground-agent.py` - PreToolUse Hook: Block foreground Agent during an active /spec Interview
├── `pretool-subagent-code-block.py` - It printed a stderr warning when a subagent whose role does not resolve to dev
├── `pretool-subagent-enforce.py` - PreToolUse:Agent Hook — Contract-driven role/pipeline enforcement (G1)
├── `pretool-subagent-time-limit.py` - The orchestrator's prompt cache lives one hour, so a subagent that returns later makes its
├── `pretool-todo-validate.py` - PreToolUse Hook: Validate TodoWrite input BEFORE execution
├── `pretool-tool-policy.py` - tool-policy.v1.json for all subagents
├── `pretool-workflow-gate.py` - PreToolUse Hook: Require TodoWrite/TodoRead acknowledgment before other tools
├── `pretool-worktree-guard.sh` - PreToolUse hook: Detect stale agent worktrees before ANY tool call
├── `pretool-wrapper-userintent.py` - The /stop slash command releases overnight isolation by running
├── `pretool-write-gate.py` - It replaces seven parallel hooks (hooks-audit O4) with one process: the rules of
├── `pretool-write-guard.sh` - STUB: settings.json no longer registers it (P12); hooks/pretool-write-gate.py runs its checks as the
├── `prompt-workflow.py` - UserPromptSubmit Hook: Checklist Injection for Slash Commands
├── `pull.sh` - pull.sh - Executable version of /pull command
├── `push.sh` - push.sh - Executable version of /push command
├── `QUICKSTART.md` - Quick Start — the hooks layer
├── `session-git-init.sh` - Ensure Git Repository Hook for Claude Code
├── `session-gitignore-propagate.sh` - SessionStart hook: keep the harness's runtime directories out of a product repo's git status.
├── `session-info.sh` - session-info.sh — SessionStart: the session's directory, git state and project metadata, for the model.
├── `session-promote-hook.sh` - Description: SessionStart hook that promotes a cold session back to ramdisk.
├── `session-scratch-init.sh` - session-scratch-init.sh — SessionStart hook (Scratch Lifecycle Contract
├── `session-tmpfs-banner.sh` - session-tmpfs-banner.sh — SessionStart hook: the space notice of hooks/userprompt-tmpfs-pressure.sh, at
├── `sessionend-scratch-sweep.sh` - sessionend-scratch-sweep.sh — SessionEnd hook (Scratch Lifecycle Contract
├── `sessionstart-launch.py` - Every Python hook registered on SessionStart runs here, each as `python3 <file>` would have run it
├── `stop-cleanup-allowlist.sh` - Stop Hook: reap every /allow grant the reader rejects at turn end.
├── `stop-command-gate.py` - The Stop coordinator's completion phase runs it with its mode
├── `stop-launch.py` - stderr. When the coordinator cannot decide (another exit, a timeout, a launch error, a missing
├── `stop-spec-coverage-enforce.py` - It ran spec-verify.py on the views of the spec the /spec session last wrote, at
├── `stop-workflow-coordinator.py` - LANE-B (20260808-035658) M4/M7, P5 R9: run by hooks/stop-launch.py (directly by a session that
├── `stop.sh` - stop.sh - wrapper for /stop slash command
├── `subagent-stop-diff-check.sh` - STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
├── `subagent-stop-guard-integrity.sh` - STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
├── `subagentstart-launch.py` - Every Python hook registered on SubagentStart runs here, each as `python3 <file>` would have run it
├── `subagentstart-record.py` - rank's reminder (hooks/lib/score_log.py), as additionalContext of at most 3 lines and 400 bytes; ...
├── `subagentstart-scratch.py` - (lib/locations.py session_scratch_dir; hooks/pretool-tool-policy.py judges it the agent's own), b...
├── `subagentstop-artifact-contract-enforce.py` - The stopping subagent's own dispatch obligation (hooks/lib/obligation.py)
├── `subagentstop-codex-enforce.py` - Activation logic:
├── `subagentstop-cp-enforce.py` - Description: SubagentStop hook for spec checkpoint enforcement (W6).
├── `subagentstop-e2e-enforce.py` - Activation logic:
├── `subagentstop-lane-blockers.py` - A non-empty `blocking_issues` in a dev report holds the whole command at the
├── `subagentstop-producer-gate.py` - The rules run in this order, each as its own hook would run alone (its switch, its
├── `subagentstop-restart-track.py` - SubagentStop: persist response evidence for a /restart-resumed agent.
├── `userprompt-auto-targets.py` - commands/commit.md and close.md say the --auto snapshot is frozen for the batch; this rule makes ...
├── `userprompt-bulk-commit-capability.py` - human prompt, NOT from an LLM-emitted Bash command
├── `userprompt-consent-allowlist.sh` - UserPromptSubmit Hook: the owner's /allow grant, and its end at the owner's next prompt.
├── `userprompt-doc-sync-check.py` - UserPromptSubmit Hook: Periodic file deletion detection for doc-sync
├── `userprompt-harness-switch.sh` - userprompt-harness-switch.sh — UserPromptSubmit: the owner's typed /harness off|on|status.
├── `userprompt-launch.py` - Every Python hook registered on UserPromptSubmit runs here, each as `python3 <file>` would have r...
├── `userprompt-restart-authorize.py` - the /dev-overnight session's own wake (lib.overnight.WAKE_PROMPT) inside its open span
├── `userprompt-returns-deadline.sh` - UserPromptSubmit, asyncRewake: the deadline of a batch of held background returns (hooks/lib/returns_hold.py,
├── `userprompt-tmpfs-pressure.sh` - userprompt-tmpfs-pressure.sh — UserPromptSubmit hook; hooks/session-tmpfs-banner.sh runs it at SessionStart.
└── `userprompt-usage-snapshot.py` - Passively injects a per-account usage snapshot (available/exhausted status,
```
<!-- /AUTO:index-stats -->

---
*Auto-generated by doc-sync hook.*