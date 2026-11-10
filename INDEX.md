# dot-claude

<!-- AUTO:index-stats -->
*Last updated: 2026-11-10T08:16:38Z*
**Total entries**: 882
**Convention**: kebab

## Tree
```
dot-claude/
├── agents/
│   ├── shared/
│   │   ├── `no-phases.md` - No phases, no deferral
│   │   └── `specialist-protocol.md` - Specialist protocol (architect, product-owner, ui-specialist, user)
│   ├── `architect.md` - Architecture review specialist: /dev and /dev-command dispatch it at Step 3 when their specialist assessment marks it RELEVANT, and /dev-overnight at Step 3 of an exploration cycle. Identifies structural issues, technical debt, optimization opportunities, dependency problems, and pattern inconsistencies. Returns structured JSON report.
│   ├── `ba.md` - Business analyst subagent for requirements analysis and context building. Receives user requirement text, performs git analysis, identifies affected files, and returns either clarification questions or dual-format output (Markdown spec + JSON context).
│   ├── `changelog-analyst.md` - Agentic commit subagent. Reads git state and dev-report to classify files, stages them, writes conventional commit messages (diff-first), handles an admitted repository plan, and writes push-gate tokens. Dispatched exclusively by /commit.
│   ├── `cleaner.md` - Cleanup execution specialist. Executes approved cleanup actions from cleanliness-inspector, style-inspector, and prompt-inspector reports. Returns structured JSON execution report with results.
│   ├── `cleanliness-inspector.md` - File organization inspector for cleanup tasks. Detects misplaced docs, duplicates, temp files, build artifacts. Returns structured JSON report with cleanup recommendations.
│   ├── `dev.md` - Implementation specialist for development tasks. Receives rich JSON context from orchestrator, creates parameterized scripts, implements changes based on git root cause analysis. Returns structured execution report.
│   ├── `git-edge-case-analyst.md` - Git history analysis specialist. Discovers development edge cases by analyzing commits, violations, and patterns. Returns structured edge case report with prevention recommendations.
│   ├── `graphify.md` - Graphify enrichment subagent. Runs at /dev Step 9, after the BA-QA loop (Steps 7-8) and before the dev dispatch (Step 10). Refreshes the Graphify cache through graphify-maintain.py, extracts a focused subgraph from the BA blast-radius-map, and writes only its own run record and focused subgraph under .claude/dev-registry/<task_id>/graphify/; it reads the context and never writes it. Pure infrastructure agent — does NOT analyze requirements, make implementation decisions, write code, or interpret graph data for DEV.
│   ├── `merge-analyst.md` - Pre-merge analyst subagent. Inspects branch divergence, diff stat, conflict markers, and overnight-state consistency; writes a nonce-keyed merge-analyst grant (60s expiry) to <state dir>/agentic-commit/merge-analyst/. Dispatched exclusively by /merge.
│   ├── `pm.md` - Test plan manager for overnight exploration with 3 invocation modes: PLAN (build test plan via browser exploration), TRIAGE (prioritize issues from specialist reports), RETRO (retrospective analysis and cross-cycle continuity). Uses Playwright to navigate the running app in PLAN mode before writing the test plan.
│   ├── `product-owner.md` - Product-level analysis specialist: /dev and /dev-command dispatch it at Step 3 when their specialist assessment marks it RELEVANT, and /dev-overnight at Step 3 of an exploration cycle. Examines logical consistency, feature completeness, user flows, missing features, and business logic bugs. Returns structured JSON report.
│   ├── `prompt-inspector.md` - Prompt optimization inspector. Detects verbose non-functional content in command/agent documentation following 'rules not stories' principle. Returns structured JSON report with verbosity violations.
│   ├── `pull-analyst.md` - Post-pull advisory analyst subagent. Reads the new-commits range after a successful git pull --rebase and produces a structured semantic risk summary. Writes no grant and blocks nothing. Dispatched exclusively by /pull when HEAD actually changed.
│   ├── `push-analyst.md` - Pre-push analyst subagent. Inspects the commits-to-push range for sensitive files, divergence, and branch protection violations; writes a nonce-keyed push-analyst grant to <state dir>/agentic-commit/push-analyst/. Dispatched exclusively by /push.
│   ├── `qa.md` - Quality assurance specialist for verification tasks. Receives implementation report from dev subagent, validates against success criteria, runs verification scripts, identifies issues. Returns structured verification report with pass/fail status.
│   ├── `rule-inspector.md` - Folder rule discovery agent. Analyzes Git history to discover file creation patterns, extracts folder organization rules, generates INDEX.md and README.md documentation. Returns structured JSON with discovered rules.
│   ├── `spec.md` - Three-phase spec subagent. Phase 0 = read spec, decide which agents need views (free judgment). Phase 1 = content-block extraction from full monolith (verbatim byte-slices, no section pre-filtering). Phase 2 = Gawande-style checkpoint generation. Invoked by /spec command with monolith path.
│   ├── `style-inspector.md` - Development standards auditor. Enforces /dev quality standards: no hardcoding, naming conventions, venv usage, step numbering, language, script merging, documentation conciseness. Returns structured JSON report with violations.
│   ├── `test-executor.md` - Execution specialist for test infrastructure. Executes script-based and AI instruction-based tests. Returns structured execution report with results and recommendations.
│   ├── `test-validator.md` - Validation specialist for test infrastructure. Validates test syntax, dependencies, and quality before execution. Returns structured validation report.
│   ├── `test-writer.md` - Generate pytest skeleton tests from BA-produced acceptance-criteria-<task_id>.json with pytest.fail("TEST_INCOMPLETE:...") hard-stops; manage the per-task manifest tests/generated/<task_id>/manifest.json with UPDATE vs CREATE logic keyed on ac_uid hashes. Triggered by /dev when complexity_tier >= STANDARD or any tier with risk_level = high.
│   ├── `ui-specialist.md` - UI/UX review specialist: /dev and /dev-command dispatch it at Step 3 when their specialist assessment marks it RELEVANT, and /dev-overnight at Step 3 of an exploration cycle. Evaluates visual design quality, aesthetic beauty, design system adherence, styling consistency, responsive design, and component quality. Returns structured JSON report with beauty score and design quality assessment. Accessibility checks are advisory.
│   └── `user.md` - End-user simulation specialist: /dev and /dev-command dispatch it at Step 3 when their specialist assessment marks it RELEVANT, and /dev-overnight at Step 3 of an exploration cycle. Tests actual usage scenarios, checks if things work as expected, identifies UX friction, broken flows, and confusing behavior. Returns structured JSON report.
├── commands/
│   ├── `allow.md` - Single-use break-glass for one operation a declared grant-aware safety hook refused; it never overrides a settings DENY. Forms — /allow <command...> (literal, regex only when it holds true regex metacharacters), /allow --tool <literal> (always literal), or /allow re:<anchored-regex>. Bare /allow is the owner-authorized match-all selector, still single-use; every explicit selector is refused when no narrow command is derivable. A literal selector matches a positional prefix of the argument tokens, and trailing tokens become a comment the grant notice echoes. TTL 300s, consumed on any terminal result.
│   ├── `checkpoint.md` - Checkpoint Command
│   ├── `clean.md` - Aggressive project cleanup - normalize docs structure, discard tracked byproducts (old docs, one-time scripts and tests) with a recoverable git rm. Pass --codex to enable adversarial codex consultation on cleanliness-inspector and style-inspector; default is self-review only.
│   ├── `close.md` - Close the current dev cycle (agent infers task-id from conversation). Step 0 resolves the disposition and completes an unfinished cycle; QA judges and returns CLOSE YES; Step 4 asks the user to rate the cycle. --codex adds a Codex review to QA's judgment (default is QA alone); --auto closes every close_pending parent; --force is accepted and ignored.
│   ├── `codex.md` - Delegate a task to OpenAI Codex CLI (gpt-5.6-sol, xhigh reasoning) for a second opinion or parallel coding
│   ├── `commit.md` - Commit session changes via changelog-analyst subagent
│   ├── `dev-command.md` - /dev for developing a slash command, a subagent or another .claude file; the /dev workflow with the differences in this file (its own 16 steps, a singular cycle)
│   ├── `dev-overnight.md` - Autonomous overnight development loop - continuously explores codebase, finds issues, fixes them, and repeats until end-time
│   ├── `dev.md` - Orchestrated development workflow with BA subagent delegation, parallel agent execution, and iterative QA verification. Pass --codex to enable adversarial codex consultation on each subagent's draft; default is self-review only.
│   ├── `do.md` - Allow main agent to bypass orchestrator-gate restrictions for this turn (subagent-only operations become directly allowed). The next prompt clears it.
│   ├── `merge.md` - Merge any resolvable commit-ish into the default branch with a real merge that keeps the full history. Bare /merge infers the source (overnight state, then the current branch in the main checkout); /merge <ref> names it. A linked (registered_worktree) worktree is removed afterward with its merged branch and overnight-state file; in the main checkout (in_place) the tree must be clean first and the branch stays.
│   ├── `paseo-daemon.md` - paseo multi-session monitoring and three-account dynamic scheduling control plane — bootstrap of a persistent, disk-backed state machine. Human-only.
│   ├── `pull.md` - Pull Command
│   ├── `push.md` - Push Command
│   ├── `rating.md` - Show every agent's score, rank, trend and latest scored events for this project, then your latest ratings. Terminal text only; it writes nothing.
│   ├── `redev.md` - /redev is /dev when saving context — it re-enters the harness in the same conversation without repeating /dev's text and is /dev in every other respect (same arguments, steps, gates and artifacts; a fresh task id each invocation; no earlier cycle continued). Pass --codex to enable adversarial codex consultation on each subagent's draft; default is self-review only.
│   ├── `restart.md` - Resume every quota-interrupted subagent in the current Claude Code parent session from its original transcript and agent ID; when none is recoverable, continue the invoking session's own main agent.
│   ├── `spec-update.md` - Update an existing spec, continue unfinished development, or write a temp session note.
│   ├── `spec.md` - Create spec files for any dev workflow (/dev, /dev-overnight, or standalone reference). Pass --codex to enable adversarial codex consultation on each spec-subagent / QA dispatch; default is self-review only.
│   ├── `stop.md` - End this session's /dev-overnight before its end time. Typed by the human only — the typed /stop itself releases the time-lock; agents cannot self-stop.
│   ├── `test.md` - Test validation workflow with edge case detection, systematic validation, and quality enforcement
│   └── `tickets.md` - Read-only Unfuddle-style lifecycle table of every ticket/spec/lane.
├── docs/
│   ├── reference/
│   │   ├── `checkpoint-mechanism.md` - Auto-Commit / Checkpoint Mechanism
│   │   ├── `close-commit-failure-inventory-20260927.md` - /close 与 /commit 失败方式全量清单(2026-09-27)
│   │   ├── `close-commit-zero-failure-mechanism-20260928.md` - Close/commit zero-failure mechanism — converged design (2026-09-28/29)
│   │   ├── `commit-dryrun-close-gate-ruling.md` - /commit dry-run close-gate relaxation: ruling record
│   │   ├── `commit-gate-bypass-via-background-exec-20261005.md` - Commit gate bypassed by background execution — 2026-10-05
│   │   ├── `do-report-ledger-has-no-refresh-path-20261008.md` - The `/do` ledger has no refresh path, so a cycle that keeps working becomes unclosable
│   │   ├── `fswatch-quickref.md` - FSWatch Quick Reference Card
│   │   ├── `generated-tests-policy.md` - `tests/generated/` policy — tracked but ignored, on purpose
│   │   ├── `git-fswatch.md` - Git File Watcher (fswatch) Documentation
│   │   ├── `graphify-integration.md` - Graphify Knowledge Graph Integration
│   │   ├── `harness-gaps-found-20261005.md` - Harness gaps found during the 2026-10-05 tree-to-zero campaign
│   │   ├── `harness-issues-backlog.md` - harness 问题清单：/dev 会话里发现的新 harness 问题只记录于此、不在该会话修；harness 的 /spec 会话处理它们，条目的 spec 落库后删除
│   │   ├── `install-compatibility-matrix.md` - Install compatibility matrix
│   │   ├── `launch-plan.md` - Launch Plan — ROI-ranked channels, gated on recorded evidence
│   │   ├── `lock-file-handling.md` - Git Lock File Handling
│   │   ├── `merge-pipeline-blocked-steps-20261007.md` - /merge: two documented steps are unexecutable from agent context
│   │   ├── `open-findings-from-read-only-cycles-20261005.md` - Open findings from read-only cycles — extracted 2026-10-05
│   │   ├── `overnight-reference.md` - Overnight reference (maintainer-facing)
│   │   ├── `positioning.md` - Positioning
│   │   ├── `qa-status-gate-gap-orchestrator-side-20261005.md` - The QA-verdict gate does not cover the orchestrator — still open 2026-10-05
│   │   ├── `recoverable-discard-register-20261005.md` - Recoverable-discard register — 2026-10-05 tree-to-zero campaign
│   │   ├── `rename-execution-plan.md` - Rename execution plan — `awesome-claude-harness` → `claude-code-guardrails`
│   │   ├── `roadmap-decomposition-productization.md` - Roadmap: Monolith Decomposition + Productization
│   │   ├── `tmp-cleanup-convention.md` - Ad-hoc scratch directory convention
│   │   └── `venv-repair.md` - venv-repair — restoring `~/.claude/venv` when interpreter symlinks break
│   ├── `ADVERSARIAL-CORPUS.md` - Adversarial Bypass Corpus — claude-code-guardrails
│   ├── `ENFORCEMENT-LEDGER.md` - Enforcement Ledger — claude-code-guardrails
│   ├── `extending.md` - Extending the harness
│   ├── `faq.md` - FAQ
│   ├── `git-protection-kernel.md` - The git protection kernel
│   ├── `how-it-works.md` - How it works
│   ├── `installation.md` - Installation
│   ├── `overnight-pipeline.md` - The overnight pipeline
│   └── `THREAT-MODEL.md` - Threat Model — claude-code-guardrails
├── examples/
│   └── guard-demo/
│       ├── `run-demo.sh` - Description: Reproducible guard demo — a dangerous operation is BLOCKED by the
│       └── `run-hero-demo.sh` - Description: Five-beat guard demo — a real agent git push is refused pre-execution, a
├── hooks/
│   ├── doc_sync/
│   │   ├── `config.py` - The git-tracked helpers (WS5, AC-WS5-1) let the INDEX/README generators list
│   │   ├── `docker.py` - Parse docker-compose.yml and generate markdown table.
│   │   ├── `extract.py` - Extract description from various file types.
│   │   ├── `folder_doc.py` - doc-sync's regeneration, /clean's scripts/generate-folder-index.sh and
│   │   ├── `main.py` - Main entry point for doc-sync hook.
│   │   ├── `notice.py` - A skipped README, INDEX or CLAUDE.md section is a deliberate outcome (regeneration is opt-in
│   │   ├── `patch.py` - Patch CLAUDE.md dynamic sections using AUTO markers.
│   │   ├── `regen_index.py` - Regenerate INDEX.md for a directory.
│   │   ├── `regen_readme.py` - Regenerate README.md for a directory.
│   │   ├── `regions.py` - Four unrelated predicates used to decide what a file's AUTO region is (README first
│   │   └── `tree.py` - Build directory trees for INDEX.md.
│   ├── git-hooks/
│   │   ├── `post-commit-auto-push` - post-commit-auto-push file
│   │   └── `pre-commit` - pre-commit file
│   ├── git-keystone/
│   │   └── `reference-transaction` - reference-transaction file
│   ├── lib/
│   │   ├── runtime_guard/
│   │   ├── write_gate/
│   │   ├── `agent_cycle.py` - producer (posttool-codex-skill-ledger.py) and the hooks that read a cycle's
│   │   ├── `agent_resolver.py` - Refactored from pretool-subagent-code-block.py::_find_agent_type so that
│   │   ├── `allowlist.py` - The /allow grant file's one writer (write_sentinel_grant) and its readers,
│   │   ├── `attribution_journal.py` - Capture side (used by pretool-attribution-pre.py / posttool-attribution-post.py):
│   │   ├── `auto_push.sh` - auto_push.sh -- harness_auto_push, the one reader of the per-repository push switch.
│   │   ├── `bash_active_syntax_census.py` - WHY THIS MODULE EXISTS (spec-20260808-035658 LANE-POL, Must-2 "completeness
│   │   ├── `bash_context_strip.py` - This is deliberately NOT a full shell parser.  It only computes a conservative
│   │   ├── `bash_execution_boundary.py` - THE ALGEBRA (spec-20260808-035658 LANE-POL, Must-1).  Every execution-bearing
│   │   ├── `bash_write_targets.py` - Provides two public functions used by tool-policy and overnight-hook-guard:
│   │   ├── `capability_state.py` - verdict, and the INDEPENDENT (non-hook-dispatched) preactivation consumer
│   │   ├── `checkpoint-core.sh` - checkpoint-core.sh - Shared library for automated snapshot commits
│   │   ├── `claude_home.py` - Generalizes the in-repo gold-standard fail-closed self-resolution pattern
│   │   ├── `claude_home.sh` - claude_home.sh — shared "harness home" resolver (shell consumable).
│   │   ├── `close-verdict.py` - The one rule every reader of a close verdict applies: classify the close
│   │   ├── `close_rating.py` - The owner's close rating: handle() writes its row and returns the owner summary; the predicates P5's Stop gate imports.
│   │   ├── `closeout.py` - CLI:
│   │   ├── `command_span.py` - rule of which transcript record is a prompt the human typed
│   │   ├── `commit_journal.py` - WHY THIS EXISTS
│   │   ├── `commit_pipeline.py` - ONE home for the two questions the commit-authorization chain could not
│   │   ├── `contract_runtime.py` - This module is the single shared engine consumed by every contract-aware
│   │   ├── `declared_paths.py` - hooks/pretool-tool-policy.py decides who may write a path a dispatch of the
│   │   ├── `dev_loop_checks.py` - Five hooks held these checks (pretool-layer-escalation-check.sh, pretool-bisect-gate.sh,
│   │   ├── `dev_report_shard_patterns.py` - Single source for the per-worker / canonical dev-report filename regexes and
│   │   ├── `dispatch_template.py` - A dispatch made from a base template before a merge carries no obligation block
│   │   ├── `do_report.py` - `docs/dev/do-report-<task_id>.json` has one producer, the /do main agent. Every
│   │   ├── `gate_runner.py` - Claude Code starts every hook registered on an event at once, so two hooks that
│   │   ├── `git_clean_guard.py` - Classifies ONE Bash command for the fail-closed pre-clean guard woven into the
│   │   ├── `git_command_classifier.py` - Provides iter_git_invocations() — a token-aware parser that detects git
│   │   ├── `grepguard_context_strip.py` - PURPOSE (narrow, guard-specific)
│   │   ├── `harness_state_dir.py` - Hook runtime state (consent flags, grants, sentinels, bookmarks, stamps) lives
│   │   ├── `harness_state_dir.sh` - harness_state_dir.sh -- shell twin of hooks/lib/harness_state_dir.py.
│   │   ├── `interruption_signals.py` - Decides whether a subagent was cut off — and whether a usage limit did it — from
│   │   ├── `merge_grant.py` - The merge-analyst writes its grant with the Write tool at
│   │   ├── `obligation.py` - Rollout step S2 of the converged zero-failure design
│   │   ├── `overnight.py` - The state record `<main root>/.claude/overnight-state-<sid>.json` has one producer,
│   │   ├── `pol_degraded_removal_reference.ere` - ere file
│   │   ├── `policy_registry.py` - Reads the harness ``policies/tool-policy.v1.json`` (resolved via the shared
│   │   ├── `roster.py` - A role exists because ``agents/<role>.md`` exists and opens with YAML front
│   │   ├── `rule_runner.py` - A merged gate (hooks/pretool-write-gate.py) holds several rules that were
│   │   ├── `runtime_guard.py` - This file exists for backwards-compatibility with callers that invoke
│   │   ├── `schema_registry.py` - Reads schemas/registry.json once and lazily loads referenced schema files
│   │   ├── `score_events.py` - Score events from facts: sweep() appends the active span's events to the score log; observe() is the dispatch hook's entry.
│   │   ├── `score_log.py` - and views are computed on read, never stored. Rows: event {kind, ts, project, task_id, role, even...
│   │   ├── `scratch_owner.py` - hooks/session-scratch-init.sh writes <root>/<sid>/.owner = {"sid": ..., ...}. One rule reads
│   │   ├── `session_resources.py` - Every destructive operation is bound to an immutable resource session and a
│   │   ├── `spec_path.py` - One rule, two callers: prompt-workflow.py decides a /dev, /dev-command, /redev or
│   │   ├── `specialist_yield.py` - Public API:
│   │   ├── `stop-commands.json` - JSON config: GATED_COMMANDS, CONTROL_COMMANDS
│   │   ├── `stop_contract.py` - is a prompt the human typed (TC-4)
│   │   ├── `subagent.py` - is_subagent_context() and supporting helpers, for the hooks that import it
│   │   ├── `subagent_restart.py` - Claude Code persists each subagent transcript under the parent session.  This
│   │   └── `todo_canonical.py` - Shared canonical todo validation utilities
│   ├── tests/
│   │   ├── fixtures/
│   │   ├── `_fixtures_obligation_terminal.py` - hooks/tests/test_posttool_overnight_loop_terminal_gate.py (which pin that
│   │   ├── `pol_replay_harness.py` - ZERO-EXECUTION CONTRACT (LANE-POL AC-R02-06). Every ``command`` string in the
│   │   ├── `pol_sweep_generators.py` - WHY THIS FILE IS THE DELIVERABLE, NOT ITS OUTPUT (AC-R02-13). Two consecutive
│   │   ├── `retired_hooks.py` - A test that compares a merged rule with the hook it replaced (the write gate's overwrite rule with
│   │   ├── `test_aggregate_check_obligation_scope.py` - from the QA dispatch's own obligation (P3 row 12)
│   │   ├── `test_allowlist_consolidation.py` - Covers AC8 IS_SUBAGENT firewall scenarios and matching semantics invariants
│   │   ├── `test_allowlist_git_global_opts.py` - Regression cover for task 20260928-133915: `/allow git commit` could never match
│   │   ├── `test_artifact_contract_enforce.py` - G2 checks the artifacts a subagent's own dispatch obligation declares at its
│   │   ├── `test_attribution_journal.py` - break detection, verify script verdicts, torn-tail handling, seal
│   │   ├── `test_ba_qa_routing_record.py` - A BA or QA handed several issues stops before any analysis and replies `multi_issue_fanout_reques...
│   │   ├── `test_bash_execution_boundary.py` - These cover the properties the 436-case matrix cannot express on its own:
│   │   ├── `test_bash_safety_channel_script_operand.py` - script operand spelled through the quoted CLAUDE_HOME channel as the named script file it is,
│   │   ├── `test_bash_safety_context.py` - Tests strip_non_executable_contexts() in isolation, covering the main
│   │   ├── `test_bash_safety_context_rules.py` - converted to COMMAND_CONTEXT_STRIPPED in hooks/pretool-bash-safety.sh
│   │   ├── `test_bash_safety_git_clean.py` - hooks/pretool-bash-safety.sh (task dev-20260719-150041-a, lane r01-a)
│   │   ├── `test_bash_views_guard.py` - the quoted CLAUDE_HOME channel spelling P2 R6 gave every command line, as it
│   │   ├── `test_bash_write_targets_policy.py` - Execution-semantic write-target resolution at the exact sink use site.
│   │   ├── `test_blackbox_integration.py` - WHAT THIS PROVES, AND WHAT IT EXPLICITLY DOES NOT
│   │   ├── `test_block_branch_pr_worktree.py` - The hook forbids branch / PR / worktree CREATION on the Bash surface, with three
│   │   ├── `test_bulk_commit_sentinel.py` - Covers:
│   │   ├── `test_c_layer_protected_targets.py` - d1b244f0 made a shell `-c` layer fail closed: run-time text given to a program outside
│   │   ├── `test_capability_gate.py` - Every test drives the real artefacts: the library, the PreToolUse gate hook as a
│   │   ├── `test_checklist_record.py` - Every TodoWrite and Agent call the CLI ran is in the session transcript, so the
│   │   ├── `test_checkpoint_pii_gate.sh` - Regression tests for the checkpoint PII/credential hard-exclude + push gate
│   │   ├── `test_claude_config_guard.py` - /dev-command develops project slash commands, so its dev writes the command file the cycle asks
│   │   ├── `test_cli_role_own_cycle.py` - their cycle from the agent's own dispatch obligation
│   │   ├── `test_close_rating.py` - hooks/posttool-close-rating.py, the rating row's one writer and the owner summary it prints (thro...
│   │   ├── `test_close_verdict_round_open.py` - `CLOSE_FINDINGS: <n> items` is the never-landing return of a QA judging round
│   │   ├── `test_command_span.py` - The span is the records after the latest human-typed harness command outside
│   │   ├── `test_commit_artifact_rw_boundary.py` - WHY THIS FILE EXISTS
│   │   ├── `test_commit_event_pointer.py` - The privilege guard spends a grant by deleting it and, in the same step, writes one
│   │   ├── `test_commit_hook_bypass_deny.py` - Three rules, enforced for the main agent and for subagents alike and ahead of the
│   │   ├── `test_commit_journal.py` - attribution basis
│   │   ├── `test_context_v1_rules.py` - schemas/context.v1.json carries them for G2 at BA's stop (P1b rows 4 and 5)
│   │   ├── `test_contract_runtime_declared_vocab.py` - schema that declares them (P1b row 19 rule 7): the QA statuses the v1
│   │   ├── `test_contract_runtime_version_dispatch.py` - hooks/lib/contract_runtime.py (ticket 20260929-104216-a, zero-failure design
│   │   ├── `test_cp_checkin.py` - of ba-spec-20260427-194324.md (P1 view-trigger removal + P2 generation field)
│   │   ├── `test_cp_enforce_own_slot.py` - cp-state slot's pending checkpoints (P1c X6)
│   │   ├── `test_cycle_registry.py` - hooks/prompt-workflow.py mints the task id at UserPromptSubmit and arms the
│   │   ├── `test_declaring_dispatch.py` - of who owes an artifact of a task, from the task's dispatch records in every
│   │   ├── `test_dev_loop_checks.py` - - Before a dev dispatch (PreToolUse): layer escalation and bisect; after it returns (PostToolUse):
│   │   ├── `test_dispatch_template.py` - A dispatch's template is the fence of its command's file that names its
│   │   ├── `test_do_block_subagents.py` - During an active /do cycle the main agent could still dispatch dev-type
│   │   ├── `test_do_consent_landing.py` - hooks/prompt-workflow.py, the flag's one writer, writes it on a `/do ...` UserPromptSubmit into
│   │   ├── `test_do_taskid_mint.py` - Covers the root-cause fix for the do-report task-id collision (memory
│   │   ├── `test_doc_sync_folder_doc.py` - doc-sync's regeneration, /clean's generate-folder-index.sh and generate-folder-readme.sh,
│   │   ├── `test_doc_sync_hook_notices.py` - Backlog #83: a README that regen_readme() skips (no opening marker, or no closing marker)
│   │   ├── `test_doc_sync_index_notices.py` - Backlog #85: the INDEX regeneration path and the CLAUDE.md section patcher now report what
│   │   ├── `test_doc_sync_index_status.py` - Backlog #85: regen_index() returned None on every path, so nobody could tell a skipped INDEX
│   │   ├── `test_doc_sync_regen_readme_status.py` - Backlog #83: regen_readme() returned None on every path, so nobody could tell a skipped
│   │   ├── `test_doc_sync_regions.py` - Backlog #85: four unrelated marker predicates (README first occurrence, INDEX substring
│   │   ├── `test_doc_sync_update_only.py` - A Write in a product repository leaves no CLAUDE.md, INDEX.md or README.md behind that was
│   │   ├── `test_dual_runtime_lifecycle_e2e.py` - Real-entrypoint regressions for single-owner ordinary dev lifecycle.
│   │   ├── `test_e2e_enforce.py` - is judged on
│   │   ├── `test_env_configured_defaults.py` - or derived; such values come back only through the environment (normally the
│   │   ├── `test_extract.py` - Unit tests for hooks/doc_sync/extract.py — covers all 4 defects + known-file cases.
│   │   ├── `test_fail_closed_drift.py` - WHY THIS FILE EXISTS
│   │   ├── `test_g2_file_lists.py` - files Claude Code recorded the dev writing (hooks/subagentstop-artifact-
│   │   ├── `test_g2_harness_syntax.py` - artifact-contract-enforce.py, _harness_syntax) parses every file of the
│   │   ├── `test_g2_spec_views.py` - subagent's stop by `spec-verify.py --strict` on the views its dispatch declares
│   │   ├── `test_git_cmd_cross_consistency.py` - Verifies that GIT_CMD_RE (hooks/pretool-bash-safety.sh),
│   │   ├── `test_git_prefix_enumeration.py` - THE DEFECT
│   │   ├── `test_git_residual_override.py` - Background
│   │   ├── `test_git_shell_c_strings.py` - `bash -c "git commit -m y"` runs git, but the shell segment's command token is
│   │   ├── `test_gitignore_preflight_close_contract.py` - The gate previously harvested any docs/dev/dev-report-*.json cited anywhere in an
│   │   ├── `test_grant_binding.py` - hooks/pretool-tool-policy.py, beside the derived write permission and for every caller alike:
│   │   ├── `test_grep_backtrack_guard.py` - Freeze safe grep shapes and the catastrophic embedded-engine control.
│   │   ├── `test_hook_output_reaches_model.py` - The CLI (code.claude.com/docs/en/hooks): plain stdout reaches the model on SessionStart and
│   │   ├── `test_inflight_push_route.py` - COMPATIBILITY TESTS, kept only as long as hooks/pretool-tool-policy.py's _note_inflight_token_rou...
│   │   ├── `test_lane_completeness_watch.py` - fan-out's canonical aggregate (P1b E5): every lane report write runs the
│   │   ├── `test_laneb_session_resources.py` - LANE-B actor scratch, receipt, and owned-process broker tests.
│   │   ├── `test_laneb_stop_coordinator.py` - LANE-B non-destructive receipt writers and serialized Stop coordinator.
│   │   ├── `test_laneb_stop_overnight_timelock_scoping.py` - Its time-lock and wake check are the Stop gate's step 4 (hooks/stop-command-gate.py,
│   │   ├── `test_merge_grant_write_check.py` - Experiment E11: the privilege guard's merge-grant check sat behind
│   │   ├── `test_notification_idle_overnight.py` - (P12), and the file stays for a session that loaded an older hook list (D15)."""
│   │   ├── `test_obligation.py` - Covers the four implementation ACs of ticket-20260929-104216-b:
│   │   ├── `test_obligation_gate.py` - G1 is the first of five enforcement doors (spec-20260930-092323) that move
│   │   ├── `test_obligation_templates.py` - Two template forms exist: literal ``<obligation v="1">`` blocks, and the
│   │   ├── `test_one_process_gates.py` - - The runner keeps each rule's decision: a rule runs as its own hook would run alone,
│   │   ├── `test_overnight_cycle_contract.py` - - No seed file: the exploration (steps 2-4) passes the dispatch hook in cycles
│   │   ├── `test_overnight_git_config_write_guard.py` - The keystone's core.hooksPath lives in the repository's git config. bubblewrap's
│   │   ├── `test_overnight_gitenv_failclosed.py` - Two halves of one fail-open, scoped together because closing either alone leaves
│   │   ├── `test_overnight_inplace_bubblewrap.py` - Replayed in a bwrap-less in-place toy session, every removal of the git
│   │   ├── `test_overnight_one_state_reader.py` - cycle contract's one writer (P1b row 13, E13)
│   │   ├── `test_overnight_operand_scan_channel.py` - The commands run harness scripts as `bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/x.sh"`. For an
│   │   ├── `test_overnight_qa_sentinel_bind.py` - P1b E7 removed the one RW exception the boundary had under main's
│   │   ├── `test_overnight_question_deny.py` - hooks/pretool-overnight-hook-guard.py denies AskUserQuestion to every caller of
│   │   ├── `test_overnight_row13_consumers.py` - - The PM test plan, triage and retro reports and the specialists' reports are
│   │   ├── `test_overnight_state_file_write_guard.py` - overnight-state write-protection (ticket 20261001-161041-r10, AC4/AC5/AC6)
│   │   ├── `test_overnight_trace_evidence.py` - (P1b E3). Which report is inspected and which of its fields are required is
│   │   ├── `test_overnight_trace_yield.py` - (P1b row 18)
│   │   ├── `test_overnight_wake.py` - The wake is one recurring CronCreate of lib/overnight.py's WAKE_PROMPT, scheduled at Step 0 and d...
│   │   ├── `test_overnight_window.py` - window_open, closeout_gaps, stop_contract.timelock_released and the /stop helper
│   │   ├── `test_overwrite_guard.py` - The overwrite guard was never registered and was deleted with its route
│   │   ├── `test_pol_generative_sweeps.py` - AC-R02-10 .. AC-R02-16 (revision 2). Every deny-side population here is
│   │   ├── `test_posttool_checkpoint_refusal.py` - Drives hooks/posttool-git-checkpoint.sh as settings.json registers it (PostToolUse on
│   │   ├── `test_posttool_overnight_loop_terminal_gate.py` - re-checks any artifact (P1b row 3: the G4 terminal-lane block is gone)
│   │   ├── `test_pretool_push_analyst_grant_guard.py` - registers it (P12), and the file stays for a session that loaded an older hook list (D15);
│   │   ├── `test_privilege_guard_commit_file_operand.py` - The `-F` operand is taken from the shell-tokenised commit invocation and unquoted,
│   │   ├── `test_privilege_guard_fails_closed.py` - P9 renamed the classifier's git value-option set to GIT_GLOBAL_VALUE_OPTS; another
│   │   ├── `test_prompt_workflow_replay_window.py` - envelope only while its replay record is younger than 60 s, judged by the
│   │   ├── `test_prompt_workflow_turn_state.py` - hooks/prompt-workflow.py ``_clear_turn_state`` runs at every UserPromptSubmit: it removes
│   │   ├── `test_push_gate_ancestor_cross_session.sh` - Regression test for hooks/push.sh's push-gate token scan (task 20260924-031253):
│   │   ├── `test_push_no_upstream_guard.sh` - Regression test for hooks/push.sh R22 (line ~375): HAS_UPSTREAM must be
│   │   ├── `test_push_sentinel_abort.sh` - Unit test for AC1 V5: hooks/push.sh self-aborts before any real git push
│   │   ├── `test_push_typed_remote.py` - execute-push.py hands push.sh the resolved remote as its argument. The ahead count is taken against
│   │   ├── `test_reader_memos.py` - A hook that reads every dispatch of a long session asks for the same roster and
│   │   ├── `test_report_projection_contract.py` - Focused contract tests for the deterministic QA v1 report projection and the report gate.
│   │   ├── `test_residual_false_positives.py` - Context (task 20260903-residual-fp). `classify_git_command()` returns a
│   │   ├── `test_role_from_cli.py` - The role is the payload's agent_type when it carries an agent_id, else the agentType of
│   │   ├── `test_runcode_watchdog_aliases.py` - Direct lifecycle parity tests for both browser run-code provider names.
│   │   ├── `test_runtime_guard.py` - Two layers:
│   │   ├── `test_scratch_lifecycle.py` - Covers:
│   │   ├── `test_session_gitignore_propagate.py` - product repo are listed in the clone's own exclude file, one line each, and nothing else is writt...
│   │   ├── `test_skill_deny_coverage.py` - `disable-model-invocation: true` blocks the SlashCommand route only; the `Skill(<stem>:*)` entry in
│   │   ├── `test_span_lazy_reader.py` - what decides (P1b FX4: FX1's CS-1..3 and OB-2)
│   │   ├── `test_spec_path.py` - and prompt-workflow.py's one decision of a run's spec built on it, replayed at
│   │   ├── `test_state_dir_path_rule.py` - Each test pairs a state file's writer with its reader: with CLAUDE_STATE_DIR pointing
│   │   ├── `test_stop_checkpoint_noop_no_ref.py` - Drives the registered Stop hook, hooks/stop-launch.py, and the coordinator with its four default
│   │   ├── `test_stop_checkpoint_refusal.py` - Drives the registered Stop hook, hooks/stop-launch.py, and the coordinator with its four default
│   │   ├── `test_stop_command_gate.py` - The gate calls P3's disposition, P2's overnight locator and window, and P4's
│   │   ├── `test_stop_contract.py` - Pins the command tuples, the human-typed prompt rule (is_human_prompt), the
│   │   ├── `test_stop_do_report_gate.py` - The /do span is the Stop gate's (hooks/stop-command-gate.py, test_stop_command_gate.py's
│   │   ├── `test_stop_launch.py` - The launcher runs the Stop coordinator and relays it; when the coordinator cannot decide it
│   │   ├── `test_stop_md_userintent_wrapper.py` - commands/stop.md runs the release wrapper through the printed harness root. hooks/pretool-wrapper-
│   │   ├── `test_stop_obligation_gate.py` - stub (P1b row 3, D15) that settings.json no longer registers (P5 R12)
│   │   ├── `test_subagentstop_codex_enforce.py` - The codex ledger's one deciding read blocks a stopping subagent whose session
│   │   ├── `test_subagentstop_cp_enforce.py` - Armed as shipped (settings.json's env sets CP_ENFORCE_MODE=block), the hook blocks
│   │   ├── `test_test_writer_manifest_skeleton.py` - (agents/test-writer.md, agents/dev.md "Generated tests"). schemas/test-writer-manifest.v1.json
│   │   ├── `test_todo_script_fork.py` - lib.todo_canonical.run_todo_script runs a harness todo script in a fork of the
│   │   ├── `test_todo_validate_after_restart.py` - A dev subagent cut before its Agent call came back (no tool_result, or the CLI's error result aft...
│   │   ├── `test_todo_validate_in_flight.py` - The owner cannot stop his sessions: one that took up origin/master's /close before train 2 landed
│   │   ├── `test_tool_policy_contracts.py` - LANE-POL least-privilege role-policy regression matrix.
│   │   ├── `test_tool_policy_derived_permission.py` - hooks/pretool-tool-policy.py runs it before the role rows, for every caller, the main agent
│   │   ├── `test_tool_policy_protected_paths.py` - hooks/pretool-tool-policy.py refuses, before every other rule and for the main agent and every
│   │   ├── `test_unit_anchor.py` - Imports the anchor sibling module DIRECTLY (not via the _core facade) and
│   │   ├── `test_unit_config.py` - Imports the config sibling module DIRECTLY (not via the _core facade) and
│   │   ├── `test_unit_constants.py` - Imports the constants sibling module DIRECTLY (not via the _core facade) and
│   │   ├── `test_unit_find_cmds.py` - Imports the find_cmds sibling module DIRECTLY (not via the _core facade) and
│   │   ├── `test_unit_git_cmds.py` - Imports the git_cmds sibling module DIRECTLY (not via the _core facade) and
│   │   ├── `test_unit_pathmatch.py` - Imports the pathmatch sibling module DIRECTLY (not via the _core facade) and
│   │   ├── `test_unit_shell_lex.py` - Imports the shell_lex sibling module DIRECTLY (not via the _core facade's
│   │   ├── `test_userprompt_bulk_commit_capability.py` - These assertions (AC-FRESH-F-14) came from the tests of an unreachable script
│   │   ├── `test_userprompt_doc_sync_relay.py` - Backlog #83: the UserPromptSubmit hook resyncs a directory by running
│   │   ├── `test_userprompt_usage_snapshot.py` - Covers the three cache states the hook must handle (cache hit, cache expired
│   │   ├── `test_workflow_bookmark_writer.py` - <project>/.claude/workflow-<sid>.json is written by prompt-workflow.py alone (a
│   │   ├── `test_worktree_guard.py` - agent worktrees
│   │   ├── `test_write_gate.py` - - The gate sees what the guards saw: each rule's tool set is its guard's registered matcher
│   │   ├── `test_write_gate_overwrite_parity.py` - The write gate runs the Python form. The shell hook is an exit-0 stub since the gate's registration
│   │   ├── `test_write_guard_consent_process.py` - The file is an exit-0 stub since the write gate's registration landed (D15); its checks are the g...
│   │   ├── `test_write_push_gate_token.py` - changelog-analyst (under /commit) and the cleaner (under /clean) both call it after
│   │   └── `write_gate_settings.py` - At the P12 base (retired_hooks.BASE) settings.json registers 78 hooks of 77 files; the tracked file
│   ├── `auto-commit.sh` - auto-commit.sh - Stop hook: snapshot on conversation end
│   ├── `capability-canary.py` - Registered once per relied-upon lifecycle event, each registration carrying its
│   ├── `check-todo-md-sync.py` - check-todo-md-sync.py — Session-start drift detector for todo scripts
│   ├── `checkpoint.sh` - checkpoint.sh - Manual /checkpoint command
│   ├── `fswatch-manager.sh` - fswatch-manager.sh - Manage git-fswatch instances
│   ├── `git-fswatch.sh` - git-fswatch.sh - Comprehensive Git file watcher using fswatch
│   ├── `git-fswatch@.service` - service file
│   ├── `install-auto-sync.sh` - LEGACY / DO NOT USE — describes an obsolete auto-sync model.
│   ├── `install-git-hooks.sh` - LEGACY / DO NOT USE — describes an obsolete git-tracking model.
│   ├── `install-protection-all.sh` - LEGACY / DO NOT USE — describes an obsolete auto-push protection model.
│   ├── `install.sh` - LEGACY / DO NOT USE — describes an obsolete auto-commit model.
│   ├── `merge.sh` - merge.sh - wrapper for /merge slash command
│   ├── `notification-idle-overnight.py` - Its only effect was appending a record to the harness home's
│   ├── `posttool-allowlist-consume.py` - PostToolUse Hook: /allow grant consumption
│   ├── `posttool-attribution-post.py` - Pairs with pretool-attribution-pre.py via (session_id, tool_use_id). Purely
│   ├── `posttool-close-rating.py` - A question goes by its source prefix to one handler, an Agent call to the observer; no logic here
│   ├── `posttool-codex-skill-ledger.py` - Fires on every PostToolUse for the Skill tool. When tool_input.skill == "codex",
│   ├── `posttool-command-frontmatter-validate.py` - PostToolUse Hook: Validate .claude/commands/*.md frontmatter structure
│   ├── `posttool-dispatch-record.py` - The rules run in this order, each as its own hook would run alone
│   ├── `posttool-doc-sync.py` - PostToolUse Hook: keep the marked INDEX.md, README.md and CLAUDE.md sections in sync
│   ├── `posttool-git-checkpoint.sh` - posttool-git-checkpoint.sh - PostToolUse checkpoint trigger
│   ├── `posttool-git-warn.sh` - posttool-git-warn.sh - PostToolUse (Bash): after a git commit, tell the model which files it left untracked.
│   ├── `posttool-lane-completeness-watch.py` - producer of a fan-out's canonical aggregate dev-report (P1b E5). Every write
│   ├── `posttool-overnight-file-check.py` - PostToolUse:Agent Hook — Contract-driven overnight file check (G3)
│   ├── `posttool-overnight-loop.py` - PostToolUse:TodoWrite Hook: Overnight Loop Detection
│   ├── `posttool-overnight-trace.py` - Writes one JSONL trace record per Agent invocation to:
│   ├── `posttool-push-gate-token-verify.py` - The push gate stays, with its reconciliation path (owner's decision, 2026-09-05)
│   ├── `posttool-restart-sendmessage.py` - PostToolUse: record successful validated restart SendMessage calls.
│   ├── `posttool-runcode-watchdog.py` - PostToolUse Hook: Cancel timeout watchdog after browser_run_code completes
│   ├── `posttool-subagent-track.py` - PostToolUse:Agent Hook: the cycle contract's one writer (/dev-overnight)
│   ├── `posttool-todo-count.py` - It refused, after a TodoWrite had run, a list shorter than the command's
│   ├── `posttool-todo-sequence.py` - It re-checked, after a TodoWrite had run, the step rules
│   ├── `posttool-todo-tracker.py` - PostToolUse Hook: Output checklist progress after every TodoWrite call
│   ├── `pre-commit-check.sh` - pre-commit-check.sh - Detect untracked files before commit
│   ├── `pretool-aggregate-check.py` - existence before allowing the orchestrator to dispatch the QA subagent in
│   ├── `pretool-attribution-pre.py` - Phase 0 of the write-time attribution journal (see hooks/lib/attribution_journal.py)
│   ├── `pretool-bash-safety.sh` - PreToolUse Safety Hook - Warn or block before dangerous operations
│   ├── `pretool-bash-views-guard.py` - Parallels pretool-bash-safety.sh but focuses on views/cp-state write bypass
│   ├── `pretool-bisect-gate.sh` - STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
│   ├── `pretool-block-background-tasks.py` - PreToolUse hook: block background execution on Agent/Task/Bash/SendMessage/Workflow
│   ├── `pretool-block-branch-pr-worktree.py` - Policy (user directive 2026-06-04; the verbatim user directive is preserved in
│   ├── `pretool-block-enterworktree.sh` - PreToolUse hook: Block EnterWorktree tool
│   ├── `pretool-bulk-commit-detector.py` - PreToolUse Hook: Bulk-commit detector (advisory: exit 0 always)
│   ├── `pretool-capability-gate.py` - Blocks (exit 2) any protected-workflow activation route unless the host-capability
│   ├── `pretool-claude-config-guard.py` - PreToolUse Hook: Claude config (.claude/hooks + .claude/commands) protection
│   ├── `pretool-commit-dispatch-attest.py` - Writes `<state-dir>/claude-commit-dispatch-<sid>-<nonce>.json` when, and only
│   ├── `pretool-cp-checkin.py` - cp-state file read (the write is scripts/spec-check.py's `register`)
│   ├── `pretool-cp-state-write-guard.py` - Cycle-3 slim form (2026-05-14): Bash-extractor removed — 22-form adversarial
│   ├── `pretool-dispatch-gate.py` - The rules run in this order, each as its own hook would run alone (its switch, its
│   ├── `pretool-do-block-subagents.py` - PreToolUse hook: block Agent/Task dispatch from the MAIN agent while a /do
│   ├── `pretool-git-privilege-guard.py` - PreToolUse Hook: Agent git-privilege guard
│   ├── `pretool-gitignore-preflight.py` - pretool-gitignore-preflight.py — PreToolUse hook (matcher: Agent)
│   ├── `pretool-grep-backtrack-guard.py` - ROOT-CAUSE BACKGROUND (verified ground truth, 2026-06-15 host OOM)
│   ├── `pretool-layer-escalation-check.sh` - STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
│   ├── `pretool-layer-match-gate.sh` - STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
│   ├── `pretool-obligation-gate.py` - WHY THIS HOOK EXISTS:
│   ├── `pretool-orchestrator-gate.py` - PreToolUse Hook: Orchestrator Gate (Unified)
│   ├── `pretool-orchestrator-prompt-purity.py` - PreToolUse hook: Orchestrator Prompt Purity
│   ├── `pretool-overnight-hook-guard.py` - PreToolUse Hook: Overnight session file modification guard
│   ├── `pretool-push-analyst-grant-guard.py` - PreToolUse (matcher Bash): exit-0 stub kept at its registered path (D15).
│   ├── `pretool-quality-gate.py` - PreToolUse Hook: Quality gate for Write/Edit operations (advisory)
│   ├── `pretool-read-size-guard.py` - PreToolUse Hook: Read Size Guard
│   ├── `pretool-runcode-watchdog.py` - PreToolUse Hook: Start timeout watchdog for browser_run_code
│   ├── `pretool-spec-block-foreground-agent.py` - PreToolUse Hook: Block foreground Agent during an active /spec Interview
│   ├── `pretool-subagent-code-block.py` - It printed a stderr warning when a subagent whose role does not resolve to dev
│   ├── `pretool-subagent-enforce.py` - PreToolUse:Agent Hook — Contract-driven role/pipeline enforcement (G1)
│   ├── `pretool-todo-validate.py` - PreToolUse Hook: Validate TodoWrite input BEFORE execution
│   ├── `pretool-tool-policy.py` - tool-policy.v1.json for all subagents
│   ├── `pretool-workflow-gate.py` - PreToolUse Hook: Require TodoWrite/TodoRead acknowledgment before other tools
│   ├── `pretool-worktree-guard.sh` - PreToolUse hook: Detect stale agent worktrees before ANY tool call
│   ├── `pretool-wrapper-userintent.py` - fix-4 (Cycle-2, spec-20260604-204954 §7.4). The /stop slash command releases
│   ├── `pretool-write-gate.py` - It replaces seven parallel hooks (hooks-audit O4) with one process: the rules of
│   ├── `pretool-write-guard.sh` - STUB: settings.json no longer registers it (P12); hooks/pretool-write-gate.py runs its checks as the
│   ├── `prompt-workflow.py` - UserPromptSubmit Hook: Checklist Injection for Slash Commands
│   ├── `protection-status.sh` - protection-status.sh - Display protection status for all git repositories
│   ├── `pull.sh` - pull.sh - Executable version of /pull command
│   ├── `push.sh` - push.sh - Executable version of /push command
│   ├── `QUICKSTART.md` - Quick Start — the hooks layer
│   ├── `session-git-init.sh` - Ensure Git Repository Hook for Claude Code
│   ├── `session-gitignore-propagate.sh` - SessionStart hook: keep the harness's runtime directories out of a product repo's git status.
│   ├── `session-info.sh` - session-info.sh — SessionStart: the session's directory, git state and project metadata, for the model.
│   ├── `session-promote-hook.sh` - Description: SessionStart hook that promotes a cold session back to ramdisk.
│   ├── `session-scratch-init.sh` - session-scratch-init.sh — SessionStart hook (Scratch Lifecycle Contract
│   ├── `session-tmpfs-banner.sh` - session-tmpfs-banner.sh — SessionStart hook (6th in the SessionStart hooks block).
│   ├── `sessionend-scratch-sweep.sh` - sessionend-scratch-sweep.sh — SessionEnd hook (Scratch Lifecycle Contract
│   ├── `start-fswatch-all.sh` - start-fswatch-all.sh - Start fswatch monitoring for all important repositories
│   ├── `stop-cleanup-allowlist.sh` - Stop Hook: reap every /allow grant the reader rejects at turn end.
│   ├── `stop-command-gate.py` - The Stop coordinator's completion phase runs it with its mode
│   ├── `stop-completion-gate.py` - blocked compliant /dev Stops with GATE_ERROR and its only release was a
│   ├── `stop-do-report-gate.py` - It held a /do session's Stop until the do-report the consent sidecar named had
│   ├── `stop-launch.py` - stderr. When the coordinator cannot decide (another exit, a timeout, a launch error, a missing
│   ├── `stop-obligation-gate.py` - It re-validated, at the orchestrating session's Stop, the json artifacts its
│   ├── `stop-overnight-timelock.py` - It blocked the session's Stop while its overnight window was open, then after
│   ├── `stop-spec-coverage-enforce.py` - It ran spec-verify.py on the views of the spec the /spec session last wrote, at
│   ├── `stop-workflow-coordinator.py` - LANE-B (20260808-035658) M4/M7, P5 R9: run by hooks/stop-launch.py (directly by a session that
│   ├── `stop.sh` - stop.sh - wrapper for /stop slash command
│   ├── `subagent-stop-diff-check.sh` - STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
│   ├── `subagent-stop-guard-integrity.sh` - STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
│   ├── `subagentstop-artifact-contract-enforce.py` - The stopping subagent's own dispatch obligation (hooks/lib/obligation.py)
│   ├── `subagentstop-codex-enforce.py` - Activation logic:
│   ├── `subagentstop-cp-enforce.py` - Description: SubagentStop hook for spec checkpoint enforcement (W6).
│   ├── `subagentstop-e2e-enforce.py` - Activation logic:
│   ├── `subagentstop-producer-gate.py` - The rules run in this order, each as its own hook would run alone (its switch, its
│   ├── `subagentstop-restart-track.py` - SubagentStop: persist response evidence for a /restart-resumed agent.
│   ├── `userprompt-bulk-commit-capability.py` - human prompt, NOT from an LLM-emitted Bash command
│   ├── `userprompt-consent-allowlist.sh` - UserPromptSubmit Hook: parse `/allow <pattern>` and write a single-use
│   ├── `userprompt-doc-sync-check.py` - UserPromptSubmit Hook: Periodic file deletion detection for doc-sync
│   ├── `userprompt-restart-authorize.py` - the /dev-overnight session's own wake (lib.overnight.WAKE_PROMPT) inside its open span
│   ├── `userprompt-tmpfs-pressure.sh` - userprompt-tmpfs-pressure.sh — UserPromptSubmit hook (4th block, appended).
│   └── `userprompt-usage-snapshot.py` - Passively injects a per-account usage snapshot (available/exhausted status,
├── policies/
│   ├── `protected-workflow-manifest.v1.json` - Every protected workflow and activation route the host-capability handshake gates. A route inside protected_surface_prefixes but absent from routes[] is blocked fail-closed until explicitly added; a route outside every prefix is reported not_protected so the gate cannot brick tool use it was never meant to police.
│   ├── `public-core-residue-allowlist.v1.json` - Seed exemption set for scripts/check-public-core.sh section 5 (generic author-path residue gate). Set-based, NOT an aggregate-count ratchet: the key is (path, fingerprint, ordinal), so deleting one allowlisted occurrence never creates capacity for an unrelated new one. Every entry's `class` is RE-DERIVED structurally by the gate from the live line; a hand-written label that the source structure does not support is rejected. Entries were seeded from a live full-ledger scan, never from a number quoted in a spec.
│   ├── `specialist-degradation.v1.json` - JSON config: policy_version, defaults, per_specialist_overrides
│   └── `tool-policy.v1.json` - JSON config: policy_version, default_action, _shared_protected_path_prefixes, _note, roles
├── requirements/
│   ├── `py310.txt` - txt file
│   ├── `py311.txt` - txt file
│   └── `py312.txt` - txt file
├── schemas/
│   ├── `acceptance-criteria.v1.json` - BA's third deliverable (agents/ba.md Step 10): BDD acceptance criteria in executable form, consumed by test-writer (pytest skeleton generation) and transitively by QA Phase 5 (via the manifest test-writer derives from this file). additionalProperties true throughout -- the real corpus carries substantial revision/provenance metadata this schema must not reject. MICRO/SMALL-tier cycles satisfy this schema with an empty acceptance_criteria array (agents/ba.md Step 10).
│   ├── `ba-qa-report.v1.json` - QA's BA-validation verdict, docs/dev/ba-qa-report-<task_id>.json, in the shape the /dev, /dev-command and /dev-overnight templates prescribe. verdict fail loops back to BA; pass is the only exit. task_id is the identity the obligation names.
│   ├── `changelog-status.v1.json` - Validates the JSON payload of the '--- CHANGELOG-ANALYST-STATUS-BEGIN ---' / '--- CHANGELOG-ANALYST-STATUS-END ---' response block (agents/changelog-analyst.md '### Output schema' / '### Structured output sentinel'). This schema is a DESCRIPTION of an already-existing, already-correct output format (lane L7 of spec-20260930-092323) -- it formalizes the prose for obligation-block validation (schemas/obligation.v1.json's response_block artifact kind) and does not change what changelog-analyst emits. additionalProperties false at every level: a drifted/unexpected field is a shape bug worth surfacing, not silently accepted.
│   ├── `cleanliness-inspector-report.v1.json` - Report written by the cleanliness-inspector subagent (agents/cleanliness-inspector.md), dispatched by /close Step 1. Required set is the intersection of (a) the agent's own canonical Output Format block (agents/cleanliness-inspector.md:293-327: request_id/timestamp/inspector/findings/summary) and (b) its codex_consult mandate -- verified >=97% present across a live sweep of all on-disk docs/dev/cleanliness-inspector-report-*.json samples this session (ticket 20261001-161041-r11; 'findings' is a dict in 192/198 present cases, matching the agent's documented category-keyed shape). 'mode' was DELIBERATELY EXCLUDED from required (and from `properties`) after that same sweep showed it is NOT part of the agent's documented contract: it is missing from 8/204 reports, and -- more importantly -- is a string in 190 cases but a nested OBJECT in 6 real, current (2026-09/10) reports, so a `type` constraint on it would spuriously fail legitimate variants either way. additionalProperties: true lets 'mode' and every other cycle-specific field pass through unvalidated.
│   ├── `context.v1.json` - BA's context (agents/ba.md, JSON Context): the requirement, root cause analysis and development approach dev and QA read, the tier and risk that decide the test-writer dispatch, and, for STANDARD and COMPLEX tiers, the contracts' evidence, scope and localization. Checked at BA's stop (G2) against the path BA's obligation declares.
│   ├── `cycle-contract.v1.json` - The dispatches one /dev-overnight cycle allows after PM TRIAGE. Written only by the PM TRIAGE handler in hooks/posttool-subagent-track.py, when the PM TRIAGE dispatch returns, at <working root>/docs/dev/overnight/<sid>/cycle-<N>/cycle-contract.json, and never edited afterwards. Read by pretool-subagent-enforce.py at dispatch (G1) and posttool-overnight-file-check.py at collection (G3). An entry names no artifact: each dispatch's obligation declares its own.
│   ├── `dev-report.v2.json` - Per-task dev implementation report, v2: matches the REAL nested producer template (agents/dev.md:590-674 — nested dev.status, top-level baseline keys) instead of v1's flat shape. Required baseline_head_sha/baseline_dirty_snapshot mirror the live producer checks at scripts/aggregate-dev-report.py:529-546 (commit inventory #71/#72, close #20/#22; empty string is legal for both — unborn repo / clean tree). The AC-deviation sub-shape is defined here: this schema is its shape. lane/lane_set follow docs/reference/close-commit-zero-failure-mechanism-20260928.md §1.1(e)/§1.2: lane_set is required non-null when lane is a string; lane-membership (lane ∈ lane_set) is NOT expressible in Draft7 and is the later G2 echo check, deliberately not faked here. Authority: design §1.6 (schema v2 cutover).
│   ├── `do-report.v1.json` - Lightweight /do completion report. The /do main agent writes the whole report (commands/do.md Step 5) before session stop; the Stop gate (hooks/stop-command-gate.py) holds the /do until do.status is completed and its file lists equal the session's write set. Read by /close (do-report path) and /commit.
│   ├── `graphify-focused-subgraph.v1.json` - Task-scoped subgraph extracted from the global Graphify knowledge graph, focused on files in the BA blast-radius-map. Written to .claude/dev-registry/{task_id}/graphify/focused-subgraph.json by graphify-enrich.py.
│   ├── `graphify-prequery.v1.json` - Step 1.5 output from graphify-query.py. Contains structural_context extracted from the global Graphify cache before BA analysis. Status field drives BA behaviour: ok/degraded proceed, unavailable/skipped silently bypass.
│   ├── `graphify-run.v1.json` - Step 7.5 run record, written by graphify-enrich.py on every path: its status, the cache refresh, the focused subgraph extraction, and the context fingerprint /dev-overnight Step 11g compares. graphify never writes the context.
│   ├── `obligation.v1.json` - Validates the JSON payload of the <obligation v="1"> block per docs/reference/close-commit-zero-failure-mechanism-20260928.md §1.2 (the XML wrapper itself is the S2 grammar library's concern, not this schema's). additionalProperties false at the top level: G1's job is shape-rejection of drifted blocks (design M5/M7/M28); cross-version tolerance is carried by the wrapper's v attribute (M29), not by an open v1 object. Path fields (artifacts[].path, expected_absent[]) are repo-relative and traversal-free (must not start with '/', must not contain '..'); G1 re-checks at dispatch — the schema encodes the invariant so a registered grammar exists (G1 check 2). The null-task_id gate's expressible half is encoded (profile outside {ad_hoc, commit-bulk, commit-qa} forces a string task_id); commit-qa's context-dependence (bulk-context null vs task-scoped string) is enforced by G1 later, not by this schema. lane-membership (lane ∈ lane_set) is the later G2 echo check, not expressible in Draft7.
│   ├── `paseo-dossier.v1.json` - Structured sidecar validated by scripts/paseo-daemon-ledger.py dossier-validate. Fail-closed: a dossier missing any required F12 field, or carrying a malformed seven-field decision-journal record, must never become a committed generation. The dossier is an index and checkpoint ONLY — authoritative evidence remains the session transcript and hash-verified artifact files.
│   ├── `producer-question.v1.json` - Written by a ba or dev producer, in place of its report, when it needs one owner decision that the request, the code and a sensible default cannot settle: docs/dev/producer-question-<task_id>-<role>.json. The orchestrator relays it with one AskUserQuestion (options become the dialog's options, default the recommended one) and re-dispatches the same role; inside /dev-overnight nobody is asked: the orchestrator decides it (an experiment, else the default), records the decision and re-dispatches the same role. The subagentstop artifact-contract hook checks task_id and role against the dispatch's obligation and that default is one of the option labels, which JSON Schema cannot express.
│   ├── `prompt-inspector-report.v1.json` - Report written by the prompt-inspector subagent (agents/prompt-inspector.md), dispatched by /close Step 1. Required set is the intersection of (a) the agent's own canonical Output Format block (agents/prompt-inspector.md:150-179: request_id/timestamp/inspector/findings/summary) and (b) its codex_consult mandate -- verified >=97% present across a live sweep of all on-disk docs/dev/prompt-inspector-report-*.json samples this session (ticket 20261001-161041-r11; 'findings' is a list in 190/190 present cases, matching the agent's documented array shape). 'mode' was DELIBERATELY EXCLUDED from required (and from `properties`) after that same sweep showed it is NOT part of the agent's documented contract: it is missing from 17/194 reports, and is a string in 172 cases but a nested OBJECT in 5 real, current (2026-09) reports, so a `type` constraint on it would spuriously fail legitimate variants either way. additionalProperties: true lets 'mode' and every other cycle-specific field pass through unvalidated.
│   ├── `qa-report.v1.json` - QA verdict + evidence summary for a single pipeline. When ui_pipeline=true, evidence_summary.ui_evidence MUST satisfy the ui-specialist's ui_evidence_schema fragment (target_route, target_element, viewports {desktop, mobile}, evidence_map keyed AC-N, trace, captured_at). Custom keyword 'required_when_ui' is enforced by lib/contract_runtime.validate() as a pre-validation pass before the standard jsonschema Draft7Validator runs.
│   ├── `qa-report.v2.json` - QA verdict report, v2: matches the REAL nested producer (agents/qa.md:1393 — nested qa.status mandated; top-level status MUST NOT be emitted because commit.sh:547-556 reads only data['qa']['status']). Top-level verdict is likewise forbidden: no producer emits it and schemas/qa-report.v1.json:8-14 REQUIRES it, so forbidding it here shape-rejects flat v1-relic records misdeclared as report_version 2. qa.e2e_enforcement.status carries the FULL recognized vocabulary of hooks/subagentstop-e2e-enforce.py:41 (PASSING_STATUSES) plus its explicitly-recognized blocking value skipped_without_justification (:270): the schema validates SHAPE, the e2e stop gate keeps enforcing POLICY — narrowing the enum would make an honestly-reported skip a schema-forgery incentive. NO baseline_head_sha/baseline_dirty_snapshot here: the qa producer template (agents/qa.md:1398-1621) does not emit them (QA reads them from the dev report, agents/qa.md:468). lane/lane_set follow design §1.1(e)/§1.2 (lane-membership is the later G2 echo check, not schema-checked). Authority: docs/reference/close-commit-zero-failure-mechanism-20260928.md §1.6.
│   ├── `registry.json` - JSON config: schemas
│   ├── `retro-report.v1.json` - The retrospective PM writes in /dev-overnight RETRO mode (agents/pm.md, Step 9), docs/dev/overnight/<session_id>/retro-report-cycle<N>.json; G2 checks it at PM's own stop. Its presence ends the cycle (hooks/lib/overnight.py cycle_index) and the next cycle's PLAN reads its unresolved_issues. is_final_cycle carries the dispatch's FINAL_CYCLE; the final cycle's report holds final_summary. task_id is the identity the obligation names. Every other field of the PM payload is allowed.
│   ├── `specialist-report.v1.json` - The report a /dev-overnight Step 3 specialist writes, docs/dev/overnight/<session_id>/<specialist>-report.json, in the shape its own agent file declares; G2 checks it at the specialist's own stop. PM TRIAGE reads its findings: the issues array (agents/architect.md, product-owner.md, user.md), each issue carrying what triage merges and the pipelines carry, with no issue repeated; or the canonical finding channels of skills/ui-shared/report-schema.json (agents/ui-specialist.md). task_id is the identity the obligation names. Every other field is allowed.
│   ├── `style-inspector-report.v1.json` - Report written by the style-inspector subagent (agents/style-inspector.md), dispatched by /close Step 1. Required set is the intersection of (a) the agent's own canonical Output Format block (agents/style-inspector.md:598-621: request_id/timestamp/inspector/violations/summary) and (b) its separately-mandated 'codex_consult field MUST be present in all outputs' rule (agents/style-inspector.md:732) -- verified >=96% present across a live sweep of all on-disk docs/dev/style-inspector-report-*.json samples this session (ticket 20261001-161041-r11). 'mode' and 'standards_passed' were DELIBERATELY EXCLUDED from required after that same sweep showed they are NOT part of the agent's documented contract and are absent from 16-35% of real reports (mode: 71/201 missing; standards_passed: 33/201 missing) -- requiring either would spuriously fail a large fraction of legitimate reports, violating the ticket's 'required kept conservative' constraint. additionalProperties: true lets both (and every other cycle-specific field) pass through unvalidated.
│   ├── `test-plan.v1.json` - The test plan PM writes in /dev-overnight PLAN mode (agents/pm.md, Test Plan Schema), at the path its dispatch obligation declares; G2 checks it at PM's own stop. Required here is what the orchestrator and the specialists read from it: the app's URL, an assignment per specialist, the core-flow gate the user specialist owns, firsthand browser evidence unless the app was not running, and the degradation check of every recommended specialist. task_id is the identity the obligation names. Every other field of the PM payload is allowed.
│   ├── `test-writer-manifest.v1.json` - Per-task active test manifest (tests/generated/<task_id>/manifest.json). Field shapes pinned verbatim to agents/test-writer.md:90-112 (ticket 20261001-161041-r07). Registered so the test-writer obligation block can name this artifact and the generic SubagentStop obligation-mode loop in hooks/subagentstop-artifact-contract-enforce.py enforces its presence/shape -- no enforcement code changed by this registration.
│   ├── `test-writer-report.v1.json` - Per-task test-writer report (docs/dev/test-writer-report-<task_id>.json). Field shapes pinned verbatim to agents/test-writer.md:206-223 (ticket 20261001-161041-r07). Registered so hooks/lib/contract_runtime.validate_artifact_for_obligation can resolve a real schema instead of permanently returning 'skip' for an unregistered id. Consumed read-only by the generic SubagentStop obligation-mode loop in hooks/subagentstop-artifact-contract-enforce.py -- no enforcement code changed by this registration.
│   └── `triage-report.v1.json` - The triage report PM writes in /dev-overnight TRIAGE mode (agents/pm.md, Step 9), docs/dev/overnight/<session_id>/triage-report-cycle<N>.json; G2 checks it at PM's own stop. The orchestrator creates the cycle's pipelines from it through scripts/build-pipelines-from-triage.py, which joins pipeline_order to issues[].triage_index and carries each issue's description, location, severity and tier into its pipeline. task_id is the identity the obligation names. Every other field of the PM payload is allowed.
├── scripts/
│   ├── install/
│   │   ├── profiles/
│   │   ├── tests/
│   │   ├── `install` - install file
│   │   ├── `installer.py` - Subcommands: plan | apply | uninstall | snapshot
│   │   ├── `land` - land file
│   │   ├── `preflight` - preflight file
│   │   ├── `render-settings` - render-settings file
│   │   ├── `tmp-cleanup-install.sh` - /usr/local/sbin/tmp-cleanup.sh
│   │   ├── `tmpfiles-claude-scratch.conf` - conf file
│   │   ├── `tmpfiles-tmp-override.conf` - conf file
│   │   ├── `tmpfiles-var-tmp-override.conf` - conf file
│   │   └── `uninstall` - uninstall file
│   ├── lib/
│   │   ├── `attribution_adjudicator.py` - Phase D cutover: the lane-agnostic
│   │   ├── `candidate_tree.py` - An acceptance harness usually has to evaluate its criterion against neither the
│   │   ├── `make_sbom.py` - The SBOM is built from the archive's real contents, not from the source
│   │   ├── `release_membership.py` - Single source of truth shared by every consumer, so the archive builder, the
│   │   ├── `score_log.py` - Re-export of hooks/lib/score_log.py (the same file name, so it is loaded by path) for score-update.sh and score-inject.sh.
│   │   ├── `session_index.py` - A repository has exactly one shared index file (``$GIT_DIR/index``). Every session
│   │   ├── `sibling_loader.py` - ``scripts/late-repair-controller.py`` and
│   │   └── `soundness_gate.py` - HUNK-level failure attribution
│   ├── modern-git-slot/
│   ├── overnight-git/
│   │   ├── `git-policy-shim` - git-policy-shim file
│   │   └── `git-selector` - git-selector file
│   ├── spec-verify/
│   │   ├── `spec-verify-views.py` - Usage:
│   │   ├── `spec-verify.py` - Every non-blank, non-separator line from the monolith must appear
│   │   ├── `spec_verify_gated.py` - Three sibling checks that share the T5 ``is_strict_guide_mode`` gate and
│   │   ├── `spec_verify_mandate.py` - Activated only when the monolith declares ``guide_version: 1`` (or higher)
│   │   ├── `spec_verify_parsers.py` - Grammar: the regexes below, for the `## Role: <agent>` headings and `consumers:`
│   │   └── `spec_verify_summary.py` - Lives alongside `spec_verify_parsers.py` as a sibling sidecar because
│   ├── steps/
│   │   ├── `clean-merge-approvals.py` - python3 scripts/steps/clean-merge-approvals.py <request_id> <checkpoint_commit>
│   │   ├── `codex-run.py` - codex-run.py review                    [--model M]
│   │   ├── `commit-plan.py` - commit-plan.py --task-id <TASK_ID>
│   │   ├── `merge-snapshot.py` - merge-snapshot.py snapshot <ref>
│   │   ├── `paseo-bootstrap.py` - paseo-bootstrap.py start    --holder ID [--root DIR] [--ttl-seconds N] [--accounts A,B]
│   │   ├── `pull-run.py` - pull-run.py run
│   │   ├── `push-snapshot.py` - python3 scripts/steps/push-snapshot.py [--remote <name>]
│   │   ├── `spec-capture.py` - spec-capture.py design   --spec PATH --turn N --slug TITLE [--from FILE]   (design text on stdin ...
│   │   ├── `spec-finalize.py` - spec-finalize.py prepare  --spec PATH [--project-dir DIR]
│   │   ├── `test-context.py` - test-context.py validation --request-id ID [--timestamp T] [--project-root DIR]
│   │   ├── `test-prepare.py` - test-prepare.py init [--full] [--project-root DIR]
│   │   └── `test-validators.py` - test-validators.py check    [--project-root DIR]
│   ├── todo/
│   │   ├── `clean.py` - Preloaded TodoList for /clean workflow
│   │   ├── `close.py` - the same five steps under every prompt (--auto walks each step over its parents;
│   │   ├── `deep-search.py` - Python script
│   │   ├── `dev-command.py` - This todo script generates workflow steps for the BA-delegated dev-command workflow
│   │   ├── `dev-overnight.py` - Preloaded TodoList for /dev-overnight workflow
│   │   ├── `dev.py` - Preloaded TodoList for /dev workflow
│   │   ├── `do.py` - Injects the 5-step /do workflow checklist via hooks/prompt-workflow.py
│   │   ├── `redev.py` - Preloaded TodoList for /redev workflow. Delegates to dev.py (single source of truth).
│   │   ├── `reflect-search.py` - Preloaded TodoList for /reflect-search workflow
│   │   ├── `research-deep.py` - Python script
│   │   ├── `site-navigate.py` - Python script
│   │   ├── `spec.py` - Mirrors the ask.py structure in the knowledge-system scripts/todo directory
│   │   └── `test.py` - Preloaded TodoList for /test workflow
│   ├── `aggregate-dev-report.py` - Scans docs/dev/ for per-worker shard dev-reports matching a given task-id,
│   ├── `aggregate-permissions.py` - Usage: aggregate-permissions.py <qa-glob-or-dir> [pipelines.json]
│   ├── `analyze-git-edge-cases.sh` - Description: Analyze git history for edge cases from bug fix commits
│   ├── `apply-permissions.sh` - apply-permissions.sh — merge aggregated permissions JSON list into settings.json
│   ├── `blast-radius-tool.py` - Two phases:
│   ├── `bootstrap` - bootstrap file
│   ├── `break-overnight-lock.py` - The time-lock is released by the human-typed /stop record itself
│   ├── `build-pipelines-from-triage.py` - Consumes PM triage schema (issues[] keyed by triage_index + pipeline_order[] +
│   ├── `canary-verify.sh` - Description: Cache-safe canary that behaviorally verifies the four core PreToolUse hooks.
│   ├── `capability-doctor-strict.py` - Two properties this file exists to guarantee:
│   ├── `capability-handshake.py` - Proves (or refuses to claim) that this harness's hook-based security boundary is
│   ├── `capability-status-line.sh` - Description: statusLine command that renders the persistent host-capability marker.
│   ├── `capture-hero-run.py` - Description: Builds a hermetic fixture, installs one narrowly-scoped single-use grant,
│   ├── `check-enforcement-evidence.py` - Three subcommands, one consumer each:
│   ├── `check-file-references.sh` - File reference detection script - used by /clean command
│   ├── `check-late-repair-provenance.py` - Takes ONLY ``--task-id`` and ``--project-dir`` (never a caller-supplied file
│   ├── `check-overnight-reports.sh` - STUB: each specialist's dispatch obligation declares its report and schema, and G2
│   ├── `check-public-core.sh` - Description: Public/private boundary gate, the one privacy engine. Recomputes the top-level
│   ├── `check-readme-freshness.sh` - Check README.md freshness for all major folders
│   ├── `checkpoint-prune.sh` - checkpoint-prune.sh — trim refs/checkpoints/* to the most recent N commits
│   ├── `close-report-append.py` - Description: Deterministic read-append-reread-verify helper for the
│   ├── `close-route-select.py` - COMPATIBILITY CODE (live landing, D15/D25), kept like the old permission spellings of D14:
│   ├── `commit.sh` - Description: Kept, run by no command since P2 (D15: no feature is retired).
│   ├── `create-overnight-state.sh` - create-overnight-state.sh — Create overnight state file (v7 schema)
│   ├── `create-worktree.sh` - Create a git worktree from local HEAD (not origin/main).
│   ├── `derive-default-branch.sh` - Description: Resolve the repository's default branch name dynamically (handles main/master/any other).
│   ├── `detect-dead-functions.sh` - Shell script
│   ├── `detect-duplicate-content.sh` - Shell script
│   ├── `detect-merge-conflicts.sh` - Shell script
│   ├── `detect-orphan-agents.sh` - Description: Detect agents not referenced by any command
│   ├── `detect-orphan-commands.sh` - Description: Detect orphan commands (one-time patterns, no todo script, unused)
│   ├── `detect-orphan-scripts.sh` - Description: Detect scripts not referenced by any command/agent/other script
│   ├── `dev-lifecycle.py` - Derives, per on-disk task-id, a state (docs/dev/ticket-20260808-035658-lanel.md):
│   ├── `discover-folders.sh` - Description: Dynamically discover project folders excluding system directories
│   ├── `doctor` - doctor file
│   ├── `execute-push.py` - Eliminates the timing window that exists when validate + push are && -chained
│   ├── `generate-folder-index.sh` - Description: Generate INDEX.md for folder (inventory of contents)
│   ├── `generate-folder-readme.sh` - Description: Generate README.md for folder (purpose and organization rules)
│   ├── `generate-hero-status.py` - Description: One source of truth emits FIVE marker-delimited canonical regions and re-derives
│   ├── `graphify-enrich.py` - graphify-enrich.py — pre-DEV focused subgraph extractor (runs between Step 7 and Step 8)
│   ├── `graphify-maintain.py` - graphify-maintain.py — Global Graphify cache lifecycle manager (REAL CLI)
│   ├── `graphify-query.py` - graphify-query.py — deterministic pre-BA graph hydrator (runs between Step 1 and Step 2)
│   ├── `graphify_lib.py` - graphify_lib.py — shared library for Graphify knowledge-graph integration
│   ├── `install-checkpoint-refspec.sh` - install-checkpoint-refspec.sh — idempotently add refs/checkpoints/* to
│   ├── `install-git-keystone.sh` - install-git-keystone.sh — wire the git-native reference-transaction keystone
│   ├── `iterate-failed-pipelines.py` - COMPATIBILITY CODE (live landing, D15/D25), kept like the old permission spellings of D14:
│   ├── `late-repair-controller.py` - Owns the run-record lifecycle for the deliberately-invoked ``/close
│   ├── `lint-spec-id-centralization.py` - markdown from re-deriving a spec-id / views_dir / split_marker / cp_dir from a
│   ├── `measure-hero-fold.py` - Description: Renders README.md LOCALLY from the working tree in headless Chromium at the
│   ├── `migrate-test-to-tests.sh` - Description: Merge test/ folder into tests/ preserving all content (idempotent)
│   ├── `mint-git-blessed-token.sh` - mint-git-blessed-token.sh — issuer of the keystone blessed token (M12).
│   ├── `normalize-doc-names.sh` - normalize-doc-names.sh - Detect and report non-compliant documentation file names
│   ├── `orchestrator.sh` - Description: Agent orchestration coordinator for development and cleanup workflows
│   ├── `overnight-git-env.sh` - overnight-git-env.sh — prepare the overnight actor's git PATH + env (M11/AC9).
│   ├── `overnight-git-selftest.sh` - overnight-git-selftest.sh — launch git-version + symref self-test (M8, M16).
│   ├── `overnight-init.sh` - overnight-init.sh — perform the ENTIRE /dev-overnight Step 1 initialization in
│   ├── `overnight-inplace-env.sh` - overnight-inplace-env.sh — export the overnight ACTOR MARKER, and nothing else.
│   ├── `overnight-status.sh` - overnight-status.sh — Zero-LLM overnight session status query
│   ├── `paseo-daemon-ledger.py` - Deterministic CLI realizing blueprint F6/F8/F10/F11/F14 local-persistence
│   ├── `paseo-daemon-timers.py` - four paseo-daemon timer schedules (tick, ctrl-core-reinject, watchdog,
│   ├── `paseo-usage-read.mjs` - mjs file
│   ├── `plan-style-inspection.sh` - Description: Discover auditable files and split into groups for parallel style inspection
│   ├── `precommitted-recovery.sh` - Description: Recovery path helpers for nothing_to_commit_precommitted detection.
│   ├── `prune-orphaned-workflow-bookmarks.sh` - scripts/prune-orphaned-workflow-bookmarks.sh
│   ├── `qa-manifest-guard.py` - Dual-mode tool per BA spec docs/dev/ticket-20260529-081014.md M4:
│   ├── `qa-report-stale-iter-lint.py` - lacks an explicit resolution marker
│   ├── `rating-view.py` - Behind /rating: print the score log's per-agent view of the current project. Reads only; exit 0 even for a log it cannot read.
│   ├── `readme_facts.py` - Description: One module, one function per fact, one source per function. No number is typed here:
│   ├── `refine-context.sh` - STUB: the QA-fail loop re-dispatches dev with the QA report path; no context is merged any more.
│   ├── `repair-venv.sh` - repair-venv.sh — durably restore a Python venv when its bin/python3 symlink target is missing.
│   ├── `resolve-close-report.sh` - Resolve the close-report path for a given TASK_ID using subproject path-walk.
│   ├── `resolve-commit-repos.py` - The normal ``/commit`` workflow uses this helper before it writes any commit
│   ├── `resolve-dev-artifact-chain.py` - The resolver never creates, refreshes, or rewrites artifacts.  It validates the
│   ├── `resolve-dev-report.py` - Usage:
│   ├── `resolve-spec-artifacts.py` - spec-id resolver shared by /spec finalize and every /dev* consumer)
│   ├── `restart-subagents.py` - CLI bridge for the human-only /restart recovery workflow.
│   ├── `runcode-watchdog.py` - Watchdog process for browser_run_code timeout enforcement
│   ├── `scan-project.sh` - Description: Scan project structure and detect project type
│   ├── `score-inject.sh` - Description: Emit a prompt-injection text block describing an agent's current rank/range
│   ├── `score-update.sh` - Description: Update agent score by appending an entry to the lifecycle JSONL log.
│   ├── `seal-attribution-journal.py` - The repo tree (journals under state/attribution-journal/ AND the git object
│   ├── `session-index.py` - Subcommands (all take --git-root):
│   ├── `session-resources.py` - Provider-neutral CLI for the LANE-B session resource broker.
│   ├── `size-ratchet.py` - Usage:
│   ├── `spec-check.py` - Subcommands: check-in, register, checkpoints, mark, waive, status, check-out, unlock
│   ├── `spec-write.py` - Every write of a spec file runs through this script: /spec's own writes (the
│   ├── `stage-owned-hunks.py` - Stages ONLY this cycle's owned hunks within a single already-authorized file,
│   ├── `step7-spec-update.py` - Step 8 (Spec-update dispatch) reference harness — task 20260524-205206 iter-2
│   ├── `test` - test file
│   ├── `update-gitignore.sh` - update-gitignore.sh - Auto-update .gitignore with project-specific rules
│   ├── `verify-attribution-chain.py` - Folds each file's events across ALL session journals into a hash chain and
│   ├── `verify-claims.sh` - Description: Self-verifying headline-claims gate. Runs ALL THREE hero-provenance audits in
│   ├── `verify-hero-provenance.py` - Description: Re-runs the demo, normalizes both outputs and byte-diffs them; verifies raw
│   ├── `verify-release-manifest.sh` - Description: Verify a PUBLISHED release artifact end-to-end, WITHOUT rebuilding it.
│   ├── `write-bulk-commit-sentinel.py` - Invoked from commands/commit.md Step 5 (BULK=true) to authorize the
│   ├── `write-commit-grant.py` - Invoked from `commands/commit.md` Step 5 (non-bulk mode) to author a
│   ├── `write-e2e-enforce.sh` - STUB: the E2E gate (hooks/subagentstop-e2e-enforce.py) has no flag; it judges
│   ├── `write-enforce-flag.sh` - Write one or more enforcement-flag sentinels into a dev-registry session dir.
│   ├── `write-git-residual-override.py` - Answers the "could not be statically classified" refusal emitted by
│   ├── `write-push-gate-token.py` - Run after its own commit by both of the token's callers: changelog-analyst under
│   └── `write-qa-mode.sh` - STUB: P1b E7 replaced the qa_mode switch with the record: each QA dispatch's
├── skills/
│   ├── ui-anti-pattern-catalog/
│   │   └── `SKILL.md` - Apply the 58-rule anti-pattern catalog (10 Color + 5 Motion + 5 Typography + 5 Spacing + 2 Glass + 5 Heuristic + 4 UX-Writing + 5 Form + 4 Interactive + 5 Nielsen + 8 AI-slop) against a Playwright page. Outputs aesthetic_findings[] with category=hard_defect|taste_heuristic, with the SCHEMA-ENFORCED severity hard-cap on taste_heuristic at minor + advisory:true. Use during ui-specialist Phases 4.5/5/6.5.
│   ├── ui-apca-contrast/
│   │   └── `SKILL.md` - Run APCA Lc text-contrast measurement on a Playwright page in BOTH light and dark color schemes. Returns deterministic apca.* findings against rule-map.json. Use during ui-specialist Phase 6 (Accessibility).
│   ├── ui-axe-injector/
│   │   ├── vendor/
│   │   └── `SKILL.md` - Inject axe-core 4.10.0 into a Playwright page and run the WCAG 2.1 a/aa rule set; emit a single deterministic findings list against rule-map.json. Use during ui-specialist Phase 6 (Accessibility) before ui-contextual-heuristics.
│   ├── ui-beauty-score/
│   │   └── `SKILL.md` - Aggregate aesthetic_findings, automated_findings, and alignment_measurements into a single 1.0-10.0 beauty_score plus 7 weighted sub-scores and a 0.0-1.0 consistencyScore. Pure calculation step — never fails. Use during ui-specialist Phase 7 (Aggregation) AFTER all other ui-* skills have completed and BEFORE writing the final 6-channel report.
│   ├── ui-contextual-heuristics/
│   │   └── `SKILL.md` - Five LLM-driven contextual accessibility insights that axe cannot detect (heading hierarchy, link text, focus order, color reliance, decorative-as-interactive). MUST receive axe findings as input and dedup against them. Use during ui-specialist Phase 6 (Accessibility) AFTER ui-axe-injector.
│   ├── ui-shared/
│   │   ├── `anti-pattern-catalog.yml` - YAML config: rules
│   │   ├── `report-schema.json` - Schema for the ui-specialist subagent's final JSON report: 6 channels, hard_defect vs taste_heuristic findings, skill outputs, and a double-defense severity hard-cap on aesthetic_findings.
│   │   ├── `review-phases.yml` - YAML config: phase_order, phases
│   │   └── `rule-map.json` - JSON config: $schema_version, meta, rules
│   ├── ui-state-matrix/
│   │   └── `SKILL.md` - Verify presence of 7 interactive states (default / hover / focus / active / disabled / loading / error / success) on key interactive elements. Returns deterministic state.* findings + state_coverage_pct + not_applicable[]. Use during ui-specialist Phase 4 (Interactive Element Visual Testing).
│   └── ui-token-conformance/
│       └── `SKILL.md` - Conditional capability — measure design-token conformance (color/spacing/typography) of computed CSS values against a project's declared token source (DTCG / tailwind.config.js / theme.ts). If no token source is detected, emit capability_unavailable to unknowns and DO NOT raise findings on guesses. Use during ui-specialist Phase 5 (Aesthetic).
├── templates/
│   ├── prompt-includes/
│   │   ├── `anti-give-up.md` - Anti-Give-Up Discipline
│   │   ├── `checkpoint-marking.md` - Checkpoint Marking Contract
│   │   ├── `codex-consultation.md` - Codex consultation
│   │   ├── `overnight-spec-integration.md` - Overnight Spec Integration
│   │   └── `specialist-findings-intake.md` - Specialist Findings Intake Protocol
│   ├── `overnight-spec.md` - Spec: <issue_description>
│   └── `spec-template.md` - Spec: <issue_description>
├── tests/
│   ├── artifact_graph/
│   │   ├── `__main__.py` - ``python -m tests.artifact_graph <tree> <output.jsonl>``.
│   │   ├── `check.py` - `derive(tree, static, runs)` joins the static half (static_half.derive) and the
│   │   ├── `declarations.py` - the command files, the schemas' ids and enums, settings.json's hook
│   │   ├── `mdscan.py` - templates and the text a command shows the owner
│   │   ├── `model.py` - Every scanner appends plain facts to one `Findings`; `static_half.derive` turns
│   │   ├── `patterns.py` - The static half evaluates path expressions into *templates*: plain text in which
│   │   ├── `pyscan.py` - For every module it evaluates path expressions (string literals, f-strings,
│   │   ├── `runtime.py` - Every driver under tests/replay/drivers/ is replayed, each variant it offers,
│   │   ├── `shards.py` - One 4-CPU runner needs about 3,000 s for every traced replay and E1's differential: twice E2's
│   │   ├── `shparse.py` - dependency beyond the standard library
│   │   ├── `shscan.py` - Words are evaluated into the same templates as Python values (variables by
│   │   ├── `static_half.py` - `derive(tree)` reads one harness tree and returns every record the static
│   │   ├── `test_check.py` - Each test builds a small harness-shaped tree, derives the static half on it and
│   │   ├── `test_mutations.py` - Each test copies the tree under test (this checkout) to a scratch directory,
│   │   ├── `test_rule1_7.py` - declared artifact) and rule (7) (a list that repeats a declaration)
│   │   ├── `test_rule2.py` - Each test builds a small harness-shaped tree, derives the static half on it and runs the check's
│   │   ├── `test_rule4_6.py` - mutation), rule (5) (the chain function's output used verbatim) and rule (6) (a deciding read
│   │   ├── `test_sandbox_template.py` - A copied sandbox must be the built one as far as a replay can tell: the same
│   │   ├── `test_shards.py` - The plan is computed from the drivers present at run time: every driver lands
│   │   ├── `test_static_half.py` - Each test builds a small harness-shaped tree under tmp_path and checks the
│   │   └── `values.py` - A value is one of:
│   ├── fixtures/
│   │   ├── late_repair_golden/
│   │   ├── `canary-tool-policy.v1.json` - JSON config: _fixture, _purpose, _contract, policy_version, default_action
│   │   ├── `paseo-usage-envelope-20260828.json` - JSON config: _comment, type, message
│   │   └── `paseo_cron_vendor_vectors.json` - JSON config: _what, provenance, positive, negative, horizon
│   ├── instructions/
│   │   ├── `execution-guide.md` - AI Test Execution Guide
│   │   └── `validation-guide.md` - AI-Driven Validation Guide
│   ├── lint/
│   │   ├── `__main__.py` - python3 -m tests.lint [--tree DIR] [--check NAME ...]: print the findings, exit 1 on any.
│   │   ├── `checks.py` - The six checks by name, in the order the P12 plan lists them.
│   │   ├── `hooks.py` - What reaches the model (the CLI's hook contract): the stderr of an exit 2; a JSON object on
│   │   ├── `prompts.py` - The four prompt checks: hook strength, dead references, repeated blocks, emphasis.
│   │   ├── `test_lint_checks.py` - These run in the ordinary suite. The checks on this repository's own tree are in
│   │   ├── `test_lint_tree.py` - Collected only under HARNESS_LINT=1, which the baseline workflow's lint step sets; the
│   │   └── `tree.py` - The settings and ledger parsing is scripts/check-enforcement-evidence.py's own (the gate
│   ├── replay/
│   │   ├── bin/
│   │   ├── drivers/
│   │   ├── `__main__.py` - `python -m tests.replay ...`: see cli.py.
│   │   ├── `agents.py` - A pipeline driver renders a dispatch prompt from the tree under test (its
│   │   ├── `cli.py` - python -m tests.replay build --tree T --sandbox SB
│   │   ├── `cmdtext.py` - Drivers never hard-code a block's text: they take it, at run time, from the
│   │   ├── `conftest.py` - Every test that replays asks for the `replays` fixture with a marker naming what it needs:
│   │   ├── `differential.py` - A reader decides on an artifact when re-running its recorded invocation with
│   │   ├── `faults.py` - --arg fault=<kind>@<label glob>[=<what>][;<kind>@<label glob>[=<what>]...]
│   │   ├── `hookrun.py` - Selection follows the planning kit's runhook.py: a matcher that is empty or "*"
│   │   ├── `inner.py` - cli.py starts it as `python -m replay.inner <config.json>` from the sandbox's
│   │   ├── `landing.py` - The CLI keeps the hook commands it loaded at session start (the settings file a replay reads once,
│   │   ├── `norm.py` - A replay's own values (session ids, agent ids, tool-use ids, task ids, lanes,
│   │   ├── `pipeline.py` - An Orchestrator plays the main agent of one typed command, following the
│   │   ├── `recovery.py` - --arg fault=cut@<label glob>     F5, F5f: after the first step of a subagent whose label matches
│   │   ├── `replay.py` - A driver gets a Replay and works through Sessions and Actors (the main agent,
│   │   ├── `roles.py` - Each helper returns an Act.work callable, work(sub, brief, player) -> content,
│   │   ├── `routing.py` - No hook blocks here: the gap is what /close's disposition call (Step 0) or /commit's (Step 3) pri...
│   │   ├── `sandbox.py` - One scratch root holds everything a replay touches:
│   │   ├── `schemagen.py` - A simulated subagent writes each JSON artifact its obligation declares from the
│   │   ├── `scorelog.py` - Driver argument (cli.py --arg K=V; inner.py calls resweep() when it is given, after the driver ra...
│   │   ├── `sites.py` - Nothing here lists a site, a hook or a class. Enumerator reads settings.json and follows each
│   │   ├── `suite.py` - A scenario names one of P1b's drivers (tests/replay/drivers/) and its arguments. run() replays it
│   │   ├── `test_a20.py` - Every compliant scenario runs with the gate blocking: test_pipelines.py's armed settings set
│   │   ├── `test_bwrap_stand_in.py` - An in-place /dev-overnight launch refuses where `bwrap --ro-bind / / -- true` cannot run
│   │   ├── `test_codex_loop.py` - Each replay plays QA's `--codex` path against a stub Codex (tests/replay/drivers/_codex.py). The ...
│   │   ├── `test_faults.py` - is repaired at that producer's next round with no human action; the pipeline reaches its terminal
│   │   ├── `test_kept_first_line.py` - hookrun keeps a hook's output tail; for a long refusal that tail is the echoed
│   │   ├── `test_live_arming.py` - this tree's files
│   │   ├── `test_live_landing.py` - keep running with the hook list they loaded; nothing new may block a running session or an in-fli...
│   │   ├── `test_no_dead_end.py` - (i) The blocking sites are enumerated when the test runs (tests/replay/sites.py), never read from a
│   │   ├── `test_pipelines.py` - reaches its terminal, with the tree's settings ("shipped") and armed (G1-G3 block)
│   │   ├── `test_push_holds.py` - Each replay types /push after the owner's commit and the token its one writer wrote for it
│   │   ├── `test_refusals.py` - Each replay reaches one refusal of commands/merge.md or commands/push.md, played by its driver from
│   │   ├── `test_regressions.py` - R-N1 (review N1 of P7b's PR, X9) and R-V1 (reviews V1-1 and NV-1) are script-level replays. A
│   │   ├── `test_run_to_run.py` - The artifact check (tests/test_artifact_graph.py) derives its relations from traced replays,
│   │   ├── `test_score_replay.py` - The real hooks run under the shipped settings in a sandbox that has its own config directory; the...
│   │   ├── `test_trace_reduce.py` - Each case is a run-to-run difference two replays of one driver showed under load:
│   │   ├── `test_typed_corrections.py` - Each replay types the command with an argument that names nothing: /close of a ticket path of ano...
│   │   ├── `trace.py` - The replay runs under `strace -f --seccomp-bpf -z -y` tracing opens (with
│   │   └── `wake.py` - Modeled CLI behaviour and its sources (none of it measured on a harness host):
│   ├── score-inject-contract/
│   │   └── `test-inject-branches.sh` - Description: Verify scripts/score-inject.sh emits INJECTION_PROOF block with
│   ├── score-lifecycle-contract/
│   │   └── `test-lifecycle-cas.sh` - Description: Verify CAS and append-only invariants for scripts/score-update.sh and
│   ├── scripts/
│   │   ├── `validate-checklist-completeness.py` - Validator: validate-checklist-completeness
│   │   ├── `validate-chinese-content.py` - Validator: validate-chinese-content
│   │   ├── `validate-claude-md-protection.py` - Validator: validate-claude-md-protection
│   │   ├── `validate-debug-file-age.py` - Validator: validate-debug-file-age
│   │   ├── `validate-file-naming.py` - Validator: validate-file-naming
│   │   ├── `validate-optionality-language.py` - Validator: validate-optionality-language
│   │   ├── `validate-step-numbering.py` - Validator: validate-step-numbering
│   │   ├── `validate-todowrite-requirement.py` - Validator: validate-todowrite-requirement
│   │   ├── `validate-venv-usage.py` - Validator: validate-venv-usage
│   │   └── `validate-workflow-json-cleanup.py` - Validator: validate-workflow-json-cleanup
│   ├── `_dev_lifecycle_fixtures.py` - NOT a test file itself (no test_ prefix, not collected by pytest). Imported by
│   ├── `_late_repair_fixtures.py` - Not collected by pytest (leading underscore).  Builds four representative
│   ├── `fresh-clone-bootstrap-smoke.sh` - Description: Fresh-clone bootstrap smoke — proves "core is runnable + guards engaged"
│   ├── `test_ac_deviation_fanout_consumer.py` - lanes that stop short of ``completed`` and the lifecycle row of a chain
│   ├── `test_ac_deviation_record_chain.py` - A dev report that records an acceptance-criteria deviation is reported
│   ├── `test_aggregate_dev_report.py` - Unit tests for scripts/aggregate-dev-report.py
│   ├── `test_aggregate_dev_report_superseded_rounds.py` - aggregate dev-report's ownership-completeness check over a multi-lane,
│   ├── `test_apply_permissions.py` - /dev and /dev-command apply the permissions QA validated with the line their permission step
│   ├── `test_artifact_graph.py` - The check (tests/artifact_graph/check.py) replays every driver under
│   ├── `test_auto_push_per_repo.py` - A repository's local git config harness.autoPush decides whether automatic pushes run for it;
│   ├── `test_bash_write_targets_verb_narrowing.py` - The library used to read a word that merely begins `cp-`/`mv-` (a checkpoint id such as `cp-01`, a
│   ├── `test_bootstrap_init.py` - Every case runs in its own temporary clone of this repository, synced to the
│   ├── `test_candidate_tree.py` - Every test builds its own throwaway git repository. None of them reads this
│   ├── `test_changelog_analyst_declaration_categories.py` - `agents/changelog-analyst.md` decides what a cycle commits by reading declaration
│   ├── `test_changelog_analyst_required_to_ship_sourcing.py` - unobtainable declaration must not be silently read as an empty one
│   ├── `test_checkpoint_provenance.py` - These modes are DORMANT: no command, agent definition, or hook invokes them by
│   ├── `test_clean_orchestrator_merge.py` - clean-merge-reports reads the three inspection reports of the request the Step 3 context
│   ├── `test_cleaner_discard.py` - Action Types table gives and prints a DISCARDED line whose recover command restores the file. The
│   ├── `test_close_command_text.py` - commands/close.md as P4 decided it: one disposition call, in-turn questions, the native rating.
│   ├── `test_close_report_append.py` - failure semantics (round-7 CRITICAL fix, ticket dev-20260919-135733)
│   ├── `test_close_route_select_compat.py` - It answers the two calls origin/master's /close Step 0 makes (commands/close.md:296 on a7d3a9f, :...
│   ├── `test_codex_workflow_gate.py` - Regression tests for Codex-native workflow-plan compatibility.
│   ├── `test_commit_multi_repo_plan.py` - Python script
│   ├── `test_commit_sh_reachability.py` - commands/dev-overnight.md:1561 previously called a bare, unqualified
│   ├── `test_completeness_channel_invariant.py` - One defect with a producer half and a consumer half:
│   ├── `test_completeness_span_accounting.py` - halves on one code path
│   ├── `test_conftest_hermetic.py` - conftest.py removes CLAUDE_PROJECT_DIR, PASEO_CONFIG_DIR, CLAUDE_HOME, CODEX_HOME,
│   ├── `test_declared_vocab_readers.py` - (P1b row 19 rule 7): the orphan-agent detector asks the command files
│   ├── `test_dev_artifact_chain_consumer_contracts.py` - Contract tests for shared /dev artifact-chain consumers.
│   ├── `test_dev_commands_no_phases.py` - Every requested outcome is delivered in the same cycle and the cycle ends only when all are done....
│   ├── `test_dev_todo_accounting.py` - Python script
│   ├── `test_discover_folders.py` - INDEX per discovered folder) leaves out the harness's own directories in a project: .claude (Claude
│   ├── `test_disposition.py` - (scripts/resolve-dev-artifact-chain.py ``disposition`` and ``--disposition``)
│   ├── `test_empty_old_string_diagnosis.py` - A real cycle emitted twenty-one ledger entries whose `old` was the empty string
│   ├── `test_git_auto_push_opt_in.py` - Guards D1: nothing pushes outside /push unless GIT_AUTO_PUSH=1. Four code paths
│   ├── `test_git_clean_guard_vectors.py` - The pre-clean WIP snapshot guard (task dev-20260719-150041-c, lane r03-c) is
│   ├── `test_graphify_enrich_outputs.py` - graphify-query.py check their results against their schemas before writing (P10 A17)
│   ├── `test_graphify_scripts.py` - tests/test_graphify_scripts.py — smoke tests for scripts/graphify_lib.py
│   ├── `test_graphify_workflow_contract.py` - tests/test_graphify_workflow_contract.py — contract tests for graphify agent registration
│   ├── `test_hero_advance_cross_check.py` - tools/demo/audit.mjs measures a line's rendered right edge on a fixed monospace grid, using
│   ├── `test_hero_demo_state_dir.py` - The hero demo honours an absolute CLAUDE_STATE_DIR end to end.
│   ├── `test_hook_rejection_retry.py` - A hook-rejected operation is never retried on the owner's answer alone: only their /allow grant (dev, paseo-daemon, clean); an operation no grant can let through is withdrawn, never left to the owner's own run.
│   ├── `test_interruption_signals.py` - Every banner asserted here was measured in the real transcript corpus under
│   ├── `test_iterate_failed_pipelines_compat.py` - It answers the call origin/master's /dev-overnight Step 17 makes (commands/dev-overnight.md:1384 ...
│   ├── `test_landing.py` - render-settings land, run from hooks/auto-commit.sh), migrate's push exclusion and the settings
│   ├── `test_late_repair_driftfree_effective_state.py` - scripts/late-repair-controller.py's ``resolve_effective_report_state`` is the
│   ├── `test_late_repair_route.py` - Covers AC-7..AC-11, AC-13, AC-14 (spec-20260907-115508-lawful-commit-channel.md,
│   ├── `test_no_phases_agent_prompts.py` - Parallel lanes inside one /dev cycle stay. Sequential phases, deferred parts and "later cycle" pl...
│   ├── `test_no_phases_spec_command.py` - Parallel lanes inside one cycle stay. A spec, a view or a hand-off note never splits a requested ...
│   ├── `test_no_phases_spec_template.py` - Everything the user requested is done in the cycle; Section 7 lists the actions that
│   ├── `test_overnight_guard_in_place_git.py` - Defect (2026-08-09): `hooks/pretool-overnight-hook-guard.py` blocked EVERY git
│   ├── `test_overnight_loop_tz.py` - Verifies the overnight loop hook compares end_time correctly against the
│   ├── `test_parent_cycle_claimant_reader.py` - THE DEFECT.  Admission to a cycle's ownership-completeness claimant set was
│   ├── `test_paseo_daemon_ledger.py` - MANDATORY pytest facade for lane 20260828-112025-b: collects EVERY test
│   ├── `test_paseo_daemon_timers.py` - scripts/paseo-daemon-timers.py (task 20260926-111239)
│   ├── `test_paseo_usage_read.py` - MANDATORY pytest facade for lane 20260828-112025-b: collects EVERY test
│   ├── `test_permission_coverage.py` - entry that covers it (P2 R6/R17, D14: entries are respelled, none granted or withdrawn)
│   ├── `test_pre_commit_dev_command_files.py` - The fail-closed pre-commit hook (hooks/git-hooks/pre-commit) lets a commit stage the
│   ├── `test_private_literal_rule.py` - pre-commit hook hooks/git-hooks/pre-commit
│   ├── `test_prompt_workflow_injection_cadence.py` - The defect: ``build_overnight_continuation`` emitted ONE payload at ONE cadence
│   ├── `test_prompt_workflow_liveness_tz.py` - Two defects, both reproduced before this suite was written:
│   ├── `test_public_core_residue_gate.py` - These are the discriminating controls for the "Make CI FAIL (not advisory) on
│   ├── `test_rating_view.py` - text, and commands/rating.md only runs that script
│   ├── `test_readme_facts.py` - names its input when it is missing
│   ├── `test_readme_regions.py` - the prose around them
│   ├── `test_refusal_record_consumers.py` - This is the module named BY NAME as `check.cli_run.harness` by AC12 and AC14 of
│   ├── `test_release_pipeline_contract.py` - verifier
│   ├── `test_resolve_dev_artifact_chain.py` - Focused tests for the read-only /dev artifact-chain resolver.
│   ├── `test_resolve_spec_artifacts.py` - resolver) + the static centralization lint (AC-B4 cases 1-12, task 20260530-092123)
│   ├── `test_restart_command.py` - End-to-end unit coverage for the human-only /restart recovery protocol.
│   ├── `test_score_events.py` - escaped and close_catch, and the observer
│   ├── `test_score_log.py` - two renderers (owner summary, /rating view); and the reader's two callers
│   ├── `test_session_index.py` - Each update-index call of scripts/lib/session_index.py's sync (the --cacheinfo one for a modified...
│   ├── `test_settings_filter.py` - applied layers, the machine-form renderer, the doctor and pre-commit checks, and the owner
│   ├── `test_settings_load.py` - take its verdict which no other test runs: the claude_home probes, installer.py's plan, and the two
│   ├── `test_size_ratchet.py` - `--measure` counts the six metrics of a committed tree; `--check --budget-ref <rev>` holds HEAD to
│   ├── `test_spec_check_agent_id_guard.py` - Lane b of task 20260921-134709. Self-contained and subprocess based: one scratch
│   ├── `test_spec_check_closed_slot.py` - task 20260921-134709)
│   ├── `test_spec_check_concurrent_marking.py` - also when hooks/pretool-cp-checkin.py runs it on a subagent's Read (harness backlog #97)
│   ├── `test_spec_update_command_contracts.py` - Contracts for the live ``/spec-update`` command policy and its history entry.
│   ├── `test_spec_verify.py` - The overlap and uniqueness rules do not count the lines the split rules route into
│   ├── `test_spec_write.py` - Each test runs the script as a subprocess against a throw-away project under
│   ├── `test_specialist_yield.py` - Tests use a tmp dir for the yield log and the bundled production policy file
│   ├── `test_stage_owned_hunks_boundary.py` - content-anchor-retry boundary/coordinate-space defect (task 20260912-015952)
│   ├── `test_step8_spec_update_markers.py` - COMMIT_STEP8_TRACE=1 emits the STEP8_* markers on stderr, and stage 4's unlinked spec is printed
│   ├── `test_steps_clean_merge_approvals.py` - cleaner's context
│   ├── `test_steps_codex_run.py` - Every test runs the real script against a stub wrapper in a temp dir (CODEX_ISO_BIN). No real cod...
│   ├── `test_steps_commit_plan.py` - repositories and temporary report files (no network, nothing read from the owner's home)."""
│   ├── `test_steps_merge_snapshot.py` - against temporary git repositories (no network, nothing read from the owner's home)."""
│   ├── `test_steps_paseo_bootstrap.py` - The script is run for real, as a subprocess, with the ledger CLI and the timers CLI behind it
│   ├── `test_steps_pull_run.py` - and its Graphify update, run for real against temporary git repositories with a local bare remote...
│   ├── `test_steps_push_snapshot.py` - Every test runs the real script in a temporary git repository (no network, nothing read from the ...
│   ├── `test_steps_spec_capture.py` - Every test runs the real script in a temp project with no network and no dependence on the runner...
│   ├── `test_steps_spec_finalize.py` - Every test runs the real script in a temp project with no network and no dependence on the runner...
│   ├── `test_steps_test_context.py` - The validation context keeps the shape agents/test-validator.md documents as its Input Format. Th...
│   ├── `test_steps_test_prepare.py` - Each case runs the real script in a temporary project; nothing touches the runner's home or the n...
│   ├── `test_steps_test_validators.py` - Step 5 used to end the command with `exit 1` on a missing folder or an empty validator set; the c...
│   ├── `test_subagentstop_e2e_enforce.py` - A QA dispatch that carries an obligation is judged on exactly the qa-report
│   ├── `test_test_command_routes.py` - /test's failure routes: no typed menu or exit option, and only executor statuses the executor emits (D23, D25).
│   ├── `test_todo_md_sync.py` - Regression tests for the session-start todo/Markdown drift detector.
│   ├── `test_todo_root.py` - A product whose scripts/todo/<command>.py and hooks/lib/close-verdict.py exist
│   ├── `test_tool_policy_note_fail_closed.py` - hooks/pretool-tool-policy.py refuses a Bash write target with exit 2 and then
│   ├── `test_verify_claims_tracked_form.py` - On an initialised home the claude-settings filter leaves the machine form in the
│   ├── `test_write_qa_mode.py` - Each QA dispatch's obligation now declares the report it owes, so no qa_mode
│   ├── `TESTING.md` - Test Topology & Runner Map (authoritative)
│   └── `verify-stop-spec-session-isolation.sh` - Checks stop-spec-coverage-enforce.py, an exit-0 stub: G2 checks the split at the spec subagent's stop.
├── tools/
│   └── demo/
│       ├── `audit.mjs` - mjs file
│       ├── `build-hero-manifest.py` - Description: Emits a trace manifest (tools/demo/manifest.schema.md) in which every
│       ├── `gen-svg.mjs` - mjs file
│       ├── `known-clipped-ledger.json` - JSON config: _doc, _not_a_blessing, _measurement, _currently_empty, _corrected_2026-08-06
│       ├── `manifest.schema.md` - Trace manifest schema
│       ├── `normalize-capture.py` - Description: Produces a COMPARISON COPY of a capture with the four non-deterministic
│       ├── `sample-hook-trace.json` - JSON config: meta, lines
│       └── `sample-trace.json` - JSON config: meta, lines
├── `AGENTS.md` - AGENTS.md
├── `ARCHITECTURE.md` - Architecture — `.claude` Safety & Release Harness
├── `CHANGELOG.md` - Changelog
├── `CLAUDE.md` - Global Claude Code Configuration
├── `conftest.py` - Root conftest — `generated` marker gate for tests/generated/.
├── `LICENSE` - LICENSE file
├── `NOTICE` - NOTICE file
├── `PUBLIC-CORE.md` - PUBLIC-CORE.md — public/private boundary manifest
├── `push.sh` - push.sh - Global pre-push checks: git identity + fetch/pull/status
├── `pytest.ini` - ini file
├── `release-membership.v1.json` - EXPLICIT release-membership manifest: the exact set of tracked paths that ship in a release archive. Membership is an edit to this file, never a silent consequence of a class rule. It is deliberately NOT 'public-core + all shared/infra': PUBLIC-CORE.md calls tests/ 'not itself the shippable harness', so a blanket class rule would drag non-shippable fixtures into the distribution. It is also not public-core-only: requirements.txt and requirements/ are shared/infra yet are required to install, so a public-core-only archive would be unusable.
├── `requirements.txt` - Python dependency manifest for the Claude Code harness venv
├── `settings.json` - Claude Code harness configuration (permissions, hooks, env)
├── `settings.machine.example.json` - JSON config: _about, _format, _modules, modules, _env
└── `VERSION` - VERSION file
```
<!-- /AUTO:index-stats -->

# .claude

---
*Auto-generated by doc-sync hook.*