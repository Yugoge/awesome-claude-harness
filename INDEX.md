# dot-claude

<!-- AUTO:index-stats -->
*Last updated: 2026-10-29T06:24:47Z*
**Total entries**: 768
**Convention**: kebab

## Tree
```
dot-claude/
├── agents/
│   ├── `architect.md` - Architecture review specialist for overnight exploration. Identifies structural issues, technical debt, optimization opportunities, dependency problems, and pattern inconsistencies. Returns structured JSON report.
│   ├── `ba.md` - Business analyst subagent for requirements analysis and context building. Receives user requirement text, performs git analysis, identifies affected files, and returns either clarification questions or dual-format output (Markdown spec + JSON context).
│   ├── `changelog-analyst.md` - Agentic commit subagent. Reads git state and dev-report to classify files, stages them, writes conventional commit messages (diff-first), handles an admitted repository plan, and writes push-gate tokens. Dispatched exclusively by /commit.
│   ├── `cleaner.md` - Cleanup execution specialist. Executes approved cleanup actions from cleanliness-inspector, style-inspector, and prompt-inspector reports. Returns structured JSON execution report with results.
│   ├── `cleanliness-inspector.md` - File organization inspector for cleanup tasks. Detects misplaced docs, duplicates, temp files, build artifacts. Returns structured JSON report with cleanup recommendations.
│   ├── `dev.md` - Implementation specialist for development tasks. Receives rich JSON context from orchestrator, creates parameterized scripts, implements changes based on git root cause analysis. Returns structured execution report.
│   ├── `git-edge-case-analyst.md` - Git history analysis specialist. Discovers development edge cases by analyzing commits, violations, and patterns. Returns structured edge case report with prevention recommendations.
│   ├── `graphify.md` - Graphify enrichment subagent. Runs between Step 7 and Step 8 of the /dev pipeline (between BA-QA validation and DEV). Refreshes the Graphify cache through graphify-maintain.py, extracts a focused subgraph from the BA blast-radius-map, and writes only its own run record and focused subgraph under .claude/dev-registry/<task_id>/graphify/; it reads the context and never writes it. Pure infrastructure agent — does NOT analyze requirements, make implementation decisions, write code, or interpret graph data for DEV.
│   ├── `merge-analyst.md` - Pre-merge analyst subagent. Inspects branch divergence, diff stat, conflict markers, and overnight-state consistency; writes a nonce-keyed merge-analyst grant (60s expiry) to <state dir>/agentic-commit/merge-analyst/. Dispatched exclusively by /merge.
│   ├── `pm.md` - Test plan manager for overnight exploration with 3 invocation modes: PLAN (build test plan via browser exploration), TRIAGE (prioritize issues from specialist reports), RETRO (retrospective analysis and cross-cycle continuity). Uses Playwright to navigate the running app in PLAN mode before writing the test plan.
│   ├── `product-owner.md` - Product-level analysis specialist for overnight exploration. Examines logical consistency, feature completeness, user flows, missing features, and business logic bugs. Returns structured JSON report.
│   ├── `prompt-inspector.md` - Prompt optimization inspector. Detects verbose non-functional content in command/agent documentation following 'rules not stories' principle. Returns structured JSON report with verbosity violations.
│   ├── `pull-analyst.md` - Post-pull advisory analyst subagent. Reads the new-commits range after a successful git pull --rebase and produces a structured semantic risk summary. Writes no grant and blocks nothing. Dispatched exclusively by /pull when HEAD actually changed.
│   ├── `push-analyst.md` - Pre-push analyst subagent. Inspects the commits-to-push range for sensitive files, divergence, and branch protection violations; writes a nonce-keyed push-analyst grant to <state dir>/agentic-commit/push-analyst/. Dispatched exclusively by /push.
│   ├── `qa.md` - Quality assurance specialist for verification tasks. Receives implementation report from dev subagent, validates against success criteria, runs verification scripts, identifies issues. Returns structured verification report with pass/fail status.
│   ├── `rule-inspector.md` - Folder rule discovery agent. Analyzes Git history to discover file creation patterns, extracts folder organization rules, generates INDEX.md and README.md documentation. Returns structured JSON with discovered rules.
│   ├── `spec.md` - Three-phase spec subagent. Phase 0 = read spec, decide which agents need views (free judgment). Phase 1 = content-block extraction from full monolith (verbatim byte-slices, no section pre-filtering). Phase 2 = Gawande-style checkpoint generation. Invoked by /spec command with monolith path.
│   ├── `style-inspector.md` - Development standards auditor. Enforces /dev quality standards: no hardcoding, naming conventions, venv usage, step numbering, language, script merging, documentation conciseness. Returns structured JSON report with violations.
│   ├── `test-executor.md` - Execution specialist for test infrastructure. Executes script-based and AI instruction-based tests. Returns structured execution report with results and recommendations.
│   ├── `test-validator.md` - Validation specialist for test infrastructure. Validates test syntax, dependencies, and quality before execution. Returns structured validation report.
│   ├── `test-writer.md` - Generate pytest skeleton tests from BA-produced acceptance-criteria-<task_id>.json with pytest.fail("TEST_INCOMPLETE:...") hard-stops; manage the per-task manifest tests/generated/<task_id>/manifest.json with UPDATE vs CREATE logic keyed on ac_uid hashes. Triggered by /dev when complexity_tier >= STANDARD or any tier with risk_level = high (per spec-20260518-225715 §5.2).
│   ├── `ui-specialist.md` - UI/UX review specialist for overnight exploration. Evaluates visual design quality, aesthetic beauty, design system adherence, styling consistency, responsive design, and component quality. Returns structured JSON report with beauty score and design quality assessment. Accessibility checks are advisory.
│   └── `user.md` - End-user simulation specialist for overnight exploration. Tests actual usage scenarios, checks if things work as expected, identifies UX friction, broken flows, and confusing behavior. Returns structured JSON report.
├── commands/
│   ├── `allow.md` - Single-use break-glass for a declared grant-aware safety hook; it never overrides a settings DENY. Forms — /allow <command...> (literal, upgraded to regex only when it contains true regex metacharacters), /allow --tool <literal> (always literal, regex off), or /allow re:<anchored-regex> (explicit regex, must be anchored). Bare /allow with no argument is the owner-authorized match-all selector, still single-use and TTL-bounded; every explicit selector is refuse-by-default when no narrow command is derivable. A literal selector matches as a POSITIONAL PREFIX of the argument tokens, not a substring. When the head token is git, repo-retargeting global options (-C, --git-dir, --work-tree, --namespace) are skipped so a short selector reaches the canonical `git -C <dir> <verb>` shape; -c / --config-env / --exec-path are never skipped and fail closed. Trailing tokens become a comment the grant notice echoes. Sentinel TTL 300s, consumed on any terminal result.
│   ├── `checkpoint.md` - Checkpoint Command
│   ├── `clean.md` - Aggressive project cleanup - normalize docs structure, archive everything, delete one-time scripts/tests. Pass --codex to enable adversarial codex consultation on cleanliness-inspector and style-inspector; default is self-review only.
│   ├── `close.md` - Close the current dev cycle (agent infers task-id from conversation). QA evaluates Workflow Integrity bullets and returns CLOSE YES/with-disclosures. Pass --codex to enable multi-round QA-codex debate; default is QA-only single-round assessment. --force is DEPRECATED -- a no-op alias of the normal path (audit-logged, skips nothing). Pass --auto to discover and sequentially close every close_pending parent (see `--auto mode` below).
│   ├── `codex.md` - Delegate a task to OpenAI Codex CLI (gpt-5.6-sol, xhigh reasoning) for a second opinion or parallel coding
│   ├── `commit.md` - Commit session changes via changelog-analyst subagent
│   ├── `dev-command.md` - Enhanced development workflow with BA subagent delegation, command development best practices, Three-Party Architecture, and comprehensive automation patterns
│   ├── `dev-overnight.md` - Autonomous overnight development loop - continuously explores codebase, finds issues, fixes them, and repeats until end-time
│   ├── `dev.md` - Orchestrated development workflow with BA subagent delegation, parallel agent execution, and iterative QA verification. Pass --codex to enable adversarial codex consultation on each subagent's draft; default is self-review only.
│   ├── `do.md` - Allow main agent to bypass orchestrator-gate restrictions for this turn (subagent-only operations become directly allowed). Auto-clears at stop.
│   ├── `merge.md` - Merge any resolvable commit-ish into the default branch, on either a linked (registered_worktree) worktree or an in_place one (the main checkout -- see commands/dev-overnight.md's isolation_kind vocabulary). On a linked worktree, the agent infers the branch from active overnight state, auto-removes the worktree, deletes the merged branch, and removes the overnight-state file. In_place, the agent merges the current (or explicit) ref directly in the main root, requires a clean tree first, and keeps the branch afterward. Bare /merge typical; explicit /merge <ref> overrides.
│   ├── `paseo-daemon.md` - paseo multi-session monitoring and three-account dynamic scheduling control plane — bootstrap of a persistent disk-backed state machine (blueprint F1–F15, amended 22-entry runtime baseline). Human-only.
│   ├── `pull.md` - Pull Command
│   ├── `push.md` - Push Command
│   ├── `redev.md` - dev workflow harness re-attach — for conversations where the /dev workflow context has already appeared; may be invoked with no new requirement text to purely re-attach the harness (canonical TodoList, gates, dev-registry, artifact conventions) to that context. Pass --codex to enable adversarial codex consultation on each subagent's draft; default is self-review only.
│   ├── `restart.md` - Resume every quota-interrupted subagent in the current Claude Code parent session from its original transcript and agent ID; when none is recoverable, continue the invoking session's own main agent.
│   ├── `spec-update.md` - Update an existing spec, continue unfinished development, or write a temp session note.
│   ├── `spec.md` - Create spec files for any dev workflow (/dev, /dev-overnight, or standalone reference). Pass --codex to enable adversarial codex consultation on each spec-subagent / QA dispatch; default is self-review only.
│   ├── `stop.md` - Cancel active overnight time-lock + workflow-enforce so the session can terminate normally. User-invoked only — agents cannot self-stop.
│   ├── `test.md` - Test validation workflow with edge case detection, systematic validation, and quality enforcement
│   └── `tickets.md` - Read-only Unfuddle-style lifecycle table of every ticket/spec/lane.
├── docs/
│   ├── reference/
│   │   ├── `attribution-journal-consumer-cutover-20261004.md` - Attribution-journal consumer cutover: APPLIED (task 20261004-001927)
│   │   ├── `attribution-journal-cutover-flip-plan-20261003.md` - Attribution-journal cutover: FLIP PLAN (Phase D, plan only)
│   │   ├── `attribution-journal-phase0-facility.md` - Write-time attribution journal — Phase 0 facility notes
│   │   ├── `bash-safety-verb-anchoring-20261008.md` - Unanchored write-verb alternations over-block reads — `pretool-bash-safety.sh`
│   │   ├── `bash-write-targets-capability-gap-20261005.md` - bash_write_targets.py capability gap: a fail-open/fail-shut pair from one resolution gap
│   │   ├── `checkpoint-mechanism.md` - Auto-Commit / Checkpoint Mechanism
│   │   ├── `claim-verification-methodology-20260925.md` - backlog claim 有效性核实方法论（2026-09-25 夜）
│   │   ├── `close-commit-failure-inventory-20260927.md` - /close 与 /commit 失败方式全量清单(2026-09-27)
│   │   ├── `close-commit-zero-failure-mechanism-20260928.md` - Close/commit zero-failure mechanism — converged design (2026-09-28/29)
│   │   ├── `codex-sandbox-verification.md` - Codex CLI Sandbox Verification Report
│   │   ├── `commit-dryrun-close-gate-ruling.md` - /commit dry-run close-gate relaxation: ruling record
│   │   ├── `commit-gate-bypass-via-background-exec-20261005.md` - Commit gate bypassed by background execution — 2026-10-05
│   │   ├── `controller-error-taxonomy-20260924.md` - 控制器错误归纳（2026-09-24 夜 spec 台席会话）
│   │   ├── `core-context-refactor-plan.md` - Core Context Refactor Plan (Plan-of-Record)
│   │   ├── `do-report-ledger-has-no-refresh-path-20261008.md` - The `/do` ledger has no refresh path, so a cycle that keeps working becomes unclosable
│   │   ├── `fswatch-quickref.md` - FSWatch Quick Reference Card
│   │   ├── `generated-tests-policy.md` - `tests/generated/` policy — tracked but ignored, on purpose
│   │   ├── `git-fswatch.md` - Git File Watcher (fswatch) Documentation
│   │   ├── `graphify-integration.md` - Graphify Knowledge Graph Integration
│   │   ├── `harness-gaps-found-20261005.md` - Harness gaps found during the 2026-10-05 tree-to-zero campaign
│   │   ├── `harness-issues-backlog.md` - 待下次 spec 处理的 harness 问题清单（当前有 harness 修复在 worktree 跑，新问题只记录不并行修）
│   │   ├── `infeasibility-without-execution-20261006.md` - An infeasibility judgment that was never executed is a hypothesis, not a finding
│   │   ├── `install-compatibility-matrix.md` - Install compatibility matrix
│   │   ├── `lane-pol-catchup-plan-20260808-035658-lanepolcatchup.md` - LANE-POL Catch-Up Plan — origin/master → fix/dev-fanout-gatekeeper-20260717
│   │   ├── `launch-plan.md` - Launch Plan — ROI-ranked channels, gated on recorded evidence
│   │   ├── `lock-file-handling.md` - Git Lock File Handling
│   │   ├── `master-origin-reconciliation-gap-20261005.md` - No history-preserving reconciliation path exists between local master and diverged origin/master
│   │   ├── `mat-doc10-writer-order.v2.json` - JSON config: schema, contract_id, spec_id, lane_id, published_by_task_id
│   │   ├── `merge-pipeline-blocked-steps-20261007.md` - /merge: two documented steps are unexecutable from agent context
│   │   ├── `monolith-split-plan.md` - Monolith Split Plan (Plan-of-Record)
│   │   ├── `open-findings-from-read-only-cycles-20261005.md` - Open findings from read-only cycles — extracted 2026-10-05
│   │   ├── `overnight-cycle-20260809-013317-shared-file-attribution-20260914.md` - Attribution of unattributed content in four shared files, cycle 20260809-013317
│   │   ├── `overnight-reference.md` - Overnight reference (maintainer-facing)
│   │   ├── `overnight-worktree-20260810-test-gaps-20261005.md` - Overnight 20260810 worktree test landing: diagnosis of 22 files
│   │   ├── `overnight-worktree-test-gaps-20261005.md` - Overnight 20260809 worktree test landing: diagnosis of 15 failures
│   │   ├── `overwrite-prohibition.md` - Prohibition on wholesale replacement of an existing file
│   │   ├── `paseo-daemon-caller-id-rollout-20261004.md` - `--caller-id` enforcement: immediate rollout, no deploy step, doc gap
│   │   ├── `paseo-daemon-concurrent-staging-triple-repro-20260904-181435-20260914.md` - Triple, independent reproduction of the shared-file concurrent-staging defect
│   │   ├── `paseo-daemon-shared-file-attribution-20260913.md` - Attribution of unattributed content in the three paseo-daemon shared files
│   │   ├── `positioning.md` - Positioning
│   │   ├── `push-gate-reconciliation-decision.md` - Push-gate reconciliation — decision to keep
│   │   ├── `qa-status-gate-gap-orchestrator-side-20261005.md` - The QA-verdict gate does not cover the orchestrator — still open 2026-10-05
│   │   ├── `recoverable-discard-register-20261005.md` - Recoverable-discard register — 2026-10-05 tree-to-zero campaign
│   │   ├── `rename-execution-plan.md` - Rename execution plan — `awesome-claude-harness` → `claude-code-guardrails`
│   │   ├── `roadmap-decomposition-productization.md` - Roadmap: Monolith Decomposition + Productization
│   │   ├── `slashcommand-quick-reference.md` - Slash Command Quick Reference
│   │   ├── `subagentstop-payload-s0-measurement-20260929.md` - SubagentStop payload availability — S0 measurement (2026-09-29)
│   │   ├── `test-suite-overhaul-plan.md` - Test Suite Overhaul Plan (Plan-of-Record)
│   │   ├── `tmp-cleanup-convention.md` - Ad-hoc scratch directory convention
│   │   ├── `venv-repair.md` - venv-repair — restoring `~/.claude/venv` when interpreter symlinks break
│   │   ├── `workflow-bookmark-orphans-20261005.md` - Root-level `workflow-*.json` bookmarks have no lifecycle management; 22/22 are orphans
│   │   ├── `workspace-disposition-criteria-20261005.md` - Workspace disposition criteria, and the five verdicts that existed only in a transcript
│   │   └── `worktree-685c203b-remaining-18-disposition-20261005.md` - Worktree `overnight-20260809-685c203b`: disposition of the remaining 18 items
│   ├── `ADVERSARIAL-CORPUS.md` - Adversarial Bypass Corpus — claude-code-guardrails
│   ├── `ENFORCEMENT-LEDGER.md` - Enforcement Ledger — claude-code-guardrails
│   └── `THREAT-MODEL.md` - Threat Model — claude-code-guardrails
├── examples/
│   └── guard-demo/
│       ├── `run-demo.sh` - Description: Reproducible guard demo — a dangerous operation is BLOCKED by the
│       └── `run-hero-demo.sh` - Description: Five-beat guard demo — a real agent git push is refused pre-execution, a
├── hooks/
│   ├── doc_sync/
│   │   ├── `claude.py` - CLAUDE.md auto-creation and patching.
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
│   │   ├── `agent_resolver.py` - Refactored from pretool-subagent-code-block.py::_find_agent_type so that
│   │   ├── `allowlist.py` - Single source of truth for the one /allow grant file and the one /do consent
│   │   ├── `attribution_journal.py` - Capture side (used by pretool-attribution-pre.py / posttool-attribution-post.py):
│   │   ├── `bash_active_syntax_census.py` - WHY THIS MODULE EXISTS (spec-20260808-035658 LANE-POL, Must-2 "completeness
│   │   ├── `bash_context_strip.py` - This is deliberately NOT a full shell parser.  It only computes a conservative
│   │   ├── `bash_execution_boundary.py` - THE ALGEBRA (spec-20260808-035658 LANE-POL, Must-1).  Every execution-bearing
│   │   ├── `bash_write_targets.py` - Provides two public functions used by tool-policy and overnight-hook-guard:
│   │   ├── `capability_state.py` - verdict, and the INDEPENDENT (non-hook-dispatched) preactivation consumer
│   │   ├── `checkpoint-core.sh` - checkpoint-core.sh - Shared library for automated snapshot commits
│   │   ├── `claude_home.py` - Generalizes the in-repo gold-standard fail-closed self-resolution pattern
│   │   ├── `claude_home.sh` - claude_home.sh — shared "harness home" resolver (shell consumable).
│   │   ├── `close-verdict.py` - The one rule every reader of a close verdict applies: classify the close
│   │   ├── `closeout.py` - CLI:
│   │   ├── `command_span.py` - The span is the records after the latest human-typed harness command outside
│   │   ├── `commit_journal.py` - WHY THIS EXISTS
│   │   ├── `commit_pipeline.py` - ONE home for the two questions the commit-authorization chain could not
│   │   ├── `contract_runtime.py` - This module is the single shared engine consumed by every contract-aware
│   │   ├── `dev_report_shard_patterns.py` - Single source for the per-worker / canonical dev-report filename regexes and
│   │   ├── `dispatch_template.py` - A dispatch made from a base template before a merge carries no obligation block
│   │   ├── `git_clean_guard.py` - Classifies ONE Bash command for the fail-closed pre-clean guard woven into the
│   │   ├── `git_command_classifier.py` - Provides iter_git_invocations() — a token-aware parser that detects git
│   │   ├── `grepguard_context_strip.py` - PURPOSE (narrow, guard-specific)
│   │   ├── `harness_state_dir.py` - Hook runtime state (consent flags, grants, sentinels, bookmarks, stamps) lives
│   │   ├── `harness_state_dir.sh` - harness_state_dir.sh -- shell twin of hooks/lib/harness_state_dir.py.
│   │   ├── `interruption_signals.py` - Decides whether a subagent was cut off — and whether a usage limit did it — from
│   │   ├── `merge_grant.py` - The merge-analyst writes its grant with the Write tool at
│   │   ├── `obligation.py` - Rollout step S2 of the converged zero-failure design
│   │   ├── `overnight.py` - The state record `<project>/.claude/overnight-state-<sid>.json` has one producer,
│   │   ├── `pol_degraded_removal_reference.ere` - ere file
│   │   ├── `policy_registry.py` - Reads the harness ``policies/tool-policy.v1.json`` (resolved via the shared
│   │   ├── `roster.py` - A role exists because ``agents/<role>.md`` exists and opens with YAML front
│   │   ├── `runtime_guard.py` - This file exists for backwards-compatibility with callers that invoke
│   │   ├── `schema_registry.py` - Reads schemas/registry.json once and lazily loads referenced schema files
│   │   ├── `scratch_owner.py` - hooks/session-scratch-init.sh writes <root>/<sid>/.owner = {"sid": ..., ...}. One rule reads
│   │   ├── `session_resources.py` - Every destructive operation is bound to an immutable resource session and a
│   │   ├── `spec_path.py` - One rule, two callers: prompt-workflow.py decides a /dev, /dev-command, /redev or
│   │   ├── `specialist_yield.py` - Public API:
│   │   ├── `stop_contract.py` - is a prompt the human typed (TC-4)
│   │   ├── `subagent.py` - Single source of truth for is_subagent_context() and supporting helpers
│   │   ├── `subagent_restart.py` - Claude Code persists each subagent transcript under the parent session.  This
│   │   └── `todo_canonical.py` - Shared canonical todo validation utilities
│   ├── tests/
│   │   ├── fixtures/
│   │   ├── `_fixtures_obligation_terminal.py` - hooks/tests/test_posttool_overnight_loop_terminal_gate.py (which pin that
│   │   ├── `pol_replay_harness.py` - ZERO-EXECUTION CONTRACT (LANE-POL AC-R02-06). Every ``command`` string in the
│   │   ├── `pol_sweep_generators.py` - WHY THIS FILE IS THE DELIVERABLE, NOT ITS OUTPUT (AC-R02-13). Two consecutive
│   │   ├── `test_allowlist_consolidation.py` - Covers AC8 IS_SUBAGENT firewall scenarios and matching semantics invariants
│   │   ├── `test_allowlist_git_global_opts.py` - Regression cover for task 20260928-133915: `/allow git commit` could never match
│   │   ├── `test_artifact_contract_enforce.py` - The hook is the producer-side port of /close's Artifact schema gate
│   │   ├── `test_attribution_adjudicator.py` - canonical aggregate view (Phase C; purely additive artifacts, nothing switched)
│   │   ├── `test_attribution_journal.py` - break detection, verify script verdicts, torn-tail handling, seal
│   │   ├── `test_baseline_snapshot_preflight.py` - agents/dev.md:535 declares that the orchestrator captures baseline_dirty_snapshot
│   │   ├── `test_bash_execution_boundary.py` - These cover the properties the 436-case matrix cannot express on its own:
│   │   ├── `test_bash_safety_context.py` - Tests strip_non_executable_contexts() in isolation, covering the main
│   │   ├── `test_bash_safety_context_rules.py` - converted to COMMAND_CONTEXT_STRIPPED in hooks/pretool-bash-safety.sh
│   │   ├── `test_bash_safety_git_clean.py` - hooks/pretool-bash-safety.sh (task dev-20260719-150041-a, lane r01-a)
│   │   ├── `test_bash_write_targets_policy.py` - Execution-semantic write-target resolution at the exact sink use site.
│   │   ├── `test_blackbox_integration.py` - WHAT THIS PROVES, AND WHAT IT EXPLICITLY DOES NOT
│   │   ├── `test_block_branch_pr_worktree.py` - The hook forbids branch / PR / worktree CREATION on the Bash surface, with three
│   │   ├── `test_bulk_commit_sentinel.py` - Covers:
│   │   ├── `test_capability_gate.py` - Every test drives the real artefacts: the library, the PreToolUse gate hook as a
│   │   ├── `test_checklist_record.py` - Every TodoWrite and Agent call the CLI ran is in the session transcript, so the
│   │   ├── `test_checkpoint_pii_gate.sh` - Regression tests for the checkpoint PII/credential hard-exclude + push gate
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
│   │   ├── `test_cycle_registry.py` - hooks/prompt-workflow.py mints the task id at UserPromptSubmit and arms the
│   │   ├── `test_declaring_dispatch.py` - of who owes an artifact of a task, from the task's dispatch records in every
│   │   ├── `test_dispatch_template.py` - A dispatch's template is the fence of its command's file that names its
│   │   ├── `test_do_block_subagents.py` - During an active /do cycle the main agent could still dispatch dev-type
│   │   ├── `test_do_taskid_mint.py` - Covers the root-cause fix for the do-report task-id collision (memory
│   │   ├── `test_doc_sync_folder_doc.py` - doc-sync's regeneration, /clean's generate-folder-index.sh and generate-folder-readme.sh,
│   │   ├── `test_doc_sync_hook_notices.py` - Backlog #83: a README that regen_readme() skips (no opening marker, or no closing marker)
│   │   ├── `test_doc_sync_index_notices.py` - Backlog #85: the INDEX regeneration path and the CLAUDE.md section patcher now report what
│   │   ├── `test_doc_sync_index_status.py` - Backlog #85: regen_index() returned None on every path, so nobody could tell a skipped INDEX
│   │   ├── `test_doc_sync_regen_readme_status.py` - Backlog #83: regen_readme() returned None on every path, so nobody could tell a skipped
│   │   ├── `test_doc_sync_regions.py` - Backlog #85: four unrelated marker predicates (README first occurrence, INDEX substring
│   │   ├── `test_dual_runtime_lifecycle_e2e.py` - Real-entrypoint regressions for single-owner ordinary dev lifecycle.
│   │   ├── `test_e2e_enforce.py` - obligation fallback (ticket 20261001-161041-r06, M1)
│   │   ├── `test_env_configured_defaults.py` - or derived; such values come back only through the environment (normally the
│   │   ├── `test_extract.py` - Unit tests for hooks/doc_sync/extract.py — covers all 4 defects + known-file cases.
│   │   ├── `test_fail_closed_drift.py` - WHY THIS FILE EXISTS
│   │   ├── `test_g2_spec_views.py` - subagent's stop by `spec-verify.py --strict` on the views its dispatch declares
│   │   ├── `test_git_cmd_cross_consistency.py` - Verifies that GIT_CMD_RE (hooks/pretool-bash-safety.sh),
│   │   ├── `test_git_prefix_enumeration.py` - THE DEFECT
│   │   ├── `test_git_residual_override.py` - Background
│   │   ├── `test_gitignore_preflight_close_contract.py` - The gate previously harvested any docs/dev/dev-report-*.json cited anywhere in an
│   │   ├── `test_grep_backtrack_guard.py` - Freeze safe grep shapes and the catastrophic embedded-engine control.
│   │   ├── `test_lane_completeness_watch.py` - fan-out's canonical aggregate (P1b E5): every lane report write runs the
│   │   ├── `test_laneb_session_resources.py` - LANE-B actor scratch, receipt, and owned-process broker tests.
│   │   ├── `test_laneb_stop_coordinator.py` - LANE-B non-destructive receipt writers and serialized Stop coordinator.
│   │   ├── `test_laneb_stop_overnight_timelock_scoping.py` - Blast-radius-map.json (dev-20260910-111227/blast-radius-map-20260808-035658-laneb)
│   │   ├── `test_merge_grant_write_check.py` - Experiment E11: the privilege guard's merge-grant check sat behind
│   │   ├── `test_obligation.py` - Covers the four implementation ACs of ticket-20260929-104216-b:
│   │   ├── `test_obligation_gate.py` - G1 is the first of five enforcement doors (spec-20260930-092323) that move
│   │   ├── `test_obligation_templates.py` - Two template forms exist: literal ``<obligation v="1">`` blocks, and the
│   │   ├── `test_overnight_gitenv_failclosed.py` - Two halves of one fail-open, scoped together because closing either alone leaves
│   │   ├── `test_overnight_one_state_reader.py` - cycle contract's one writer (P1b row 13, E13)
│   │   ├── `test_overnight_qa_sentinel_bind.py` - P1b E7 removed the one RW exception the boundary had under main's
│   │   ├── `test_overnight_row13_consumers.py` - - The PM test plan, triage and retro reports and the specialists' reports are
│   │   ├── `test_overnight_state_file_write_guard.py` - overnight-state write-protection (ticket 20261001-161041-r10, AC4/AC5/AC6)
│   │   ├── `test_overnight_trace_evidence.py` - (P1b E3). Which report is inspected and which of its fields are required is
│   │   ├── `test_overnight_trace_yield.py` - (P1b row 18)
│   │   ├── `test_overwrite_guard.py` - Every assertion drives the REAL guard as a subprocess over a synthetic
│   │   ├── `test_pol_generative_sweeps.py` - AC-R02-10 .. AC-R02-16 (revision 2). Every deny-side population here is
│   │   ├── `test_posttool_overnight_loop_terminal_gate.py` - re-checks any artifact (P1b row 3: the G4 terminal-lane block is gone)
│   │   ├── `test_privilege_guard_commit_file_operand.py` - The `-F` operand is taken from the shell-tokenised commit invocation and unquoted,
│   │   ├── `test_prompt_workflow_turn_state.py` - hooks/prompt-workflow.py ``_clear_turn_state`` runs at every UserPromptSubmit: it removes
│   │   ├── `test_push_gate_ancestor_cross_session.sh` - Regression test for hooks/push.sh's push-gate token scan (task 20260924-031253):
│   │   ├── `test_push_no_upstream_guard.sh` - Regression test for hooks/push.sh R22 (line ~375): HAS_UPSTREAM must be
│   │   ├── `test_push_sentinel_abort.sh` - Unit test for AC1 V5: hooks/push.sh self-aborts before any real git push
│   │   ├── `test_reader_memos.py` - A hook that reads every dispatch of a long session asks for the same roster and
│   │   ├── `test_regen_index_dirs_script.py` - Backlog #85: the script printed `regenerated: <INDEX>` for every directory, including the ones
│   │   ├── `test_report_projection_contract.py` - Focused contract tests for deterministic Dev/QA v1 report projections.
│   │   ├── `test_residual_false_positives.py` - Context (task 20260903-residual-fp). `classify_git_command()` returns a
│   │   ├── `test_runcode_watchdog_aliases.py` - Direct lifecycle parity tests for both browser run-code provider names.
│   │   ├── `test_runtime_guard.py` - Two layers:
│   │   ├── `test_scratch_lifecycle.py` - Covers:
│   │   ├── `test_spec_path.py` - and prompt-workflow.py's one decision of a run's spec built on it."""
│   │   ├── `test_state_dir_path_rule.py` - Each test pairs a state file's writer with its reader: with CLAUDE_STATE_DIR pointing
│   │   ├── `test_stop_checkpoint_noop_no_ref.py` - Drives the registered Stop hook, hooks/stop-workflow-coordinator.py with its four default
│   │   ├── `test_stop_checkpoint_refusal.py` - Drives the registered Stop hook, hooks/stop-workflow-coordinator.py with its four default
│   │   ├── `test_stop_contract.py` - Pins the command tuples, the human-typed prompt rule (is_human_prompt), the
│   │   ├── `test_stop_do_report_gate.py` - Covers the contract from commands/do.md Step 5: a /do session may stop only
│   │   ├── `test_stop_obligation_gate.py` - exit-0 stub (P1b row 3, Correction 6, D15)
│   │   ├── `test_subagentstop_codex_enforce.py` - The codex ledger's one deciding read blocks a stopping subagent whose session
│   │   ├── `test_todo_script_fork.py` - lib.todo_canonical.run_todo_script runs a harness todo script in a fork of the
│   │   ├── `test_tool_policy_contracts.py` - LANE-POL least-privilege role-policy regression matrix.
│   │   ├── `test_tool_policy_derived_permission.py` - hooks/pretool-tool-policy.py runs it before the role rows, for every caller, the main agent
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
│   │   └── `test_write_push_gate_token.py` - changelog-analyst (under /commit) and the cleaner (under /clean) both call it after
│   ├── `auto-commit.sh` - auto-commit.sh - Stop hook: snapshot on conversation end
│   ├── `capability-canary.py` - Registered once per relied-upon lifecycle event, each registration carrying its
│   ├── `check-todo-md-sync.py` - check-todo-md-sync.py — Session-start drift detector for todo scripts
│   ├── `checkpoint.sh` - checkpoint.sh - Manual /checkpoint command
│   ├── `fswatch-manager.sh` - fswatch-manager.sh - Manage git-fswatch instances
│   ├── `git-fswatch.sh` - git-fswatch.sh - Comprehensive Git file watcher using fswatch
│   ├── `git-fswatch@.service` - service file
│   ├── `hook-todo-injection.py` - Global PreToolUse Hook: Todo Injection for Slash Commands
│   ├── `install-auto-sync.sh` - LEGACY / DO NOT USE — describes an obsolete auto-sync model.
│   ├── `install-git-hooks.sh` - LEGACY / DO NOT USE — describes an obsolete git-tracking model.
│   ├── `install-protection-all.sh` - LEGACY / DO NOT USE — describes an obsolete auto-push protection model.
│   ├── `install.sh` - LEGACY / DO NOT USE — describes an obsolete auto-commit model.
│   ├── `merge.sh` - merge.sh - wrapper for /merge slash command
│   ├── `notification-idle-overnight.py` - Its only effect was appending a record to the harness home's
│   ├── `post-commit-warn.sh` - post-commit-warn.sh - Warn about untracked files after commit
│   ├── `post_tool_use.sh` - PostToolUse Hook - Code quality hints after file modifications
│   ├── `posttool-allowlist-consume.py` - PostToolUse Hook: /allow grant consumption
│   ├── `posttool-attribution-post.py` - Pairs with pretool-attribution-pre.py via (session_id, tool_use_id). Purely
│   ├── `posttool-codex-skill-ledger.py` - Fires on every PostToolUse for the Skill tool. When tool_input.skill == "codex",
│   ├── `posttool-command-frontmatter-validate.py` - PostToolUse Hook: Validate .claude/commands/*.md frontmatter structure
│   ├── `posttool-doc-sync.py` - PostToolUse Hook: keep the marked INDEX.md, README.md and CLAUDE.md sections in sync
│   ├── `posttool-git-checkpoint.sh` - posttool-git-checkpoint.sh - PostToolUse checkpoint trigger
│   ├── `posttool-git-warn.sh` - post-commit-warn.sh - Warn about untracked files after commit
│   ├── `posttool-lane-completeness-watch.py` - producer of a fan-out's canonical aggregate dev-report (P1b E5). Every write
│   ├── `posttool-overnight-file-check.py` - PostToolUse:Agent Hook — Contract-driven overnight file check (G3)
│   ├── `posttool-overnight-loop.py` - PostToolUse:TodoWrite Hook: Overnight Loop Detection
│   ├── `posttool-overnight-trace.py` - Writes one JSONL trace record per Agent invocation to:
│   ├── `posttool-push-gate-token-verify.py` - PostToolUse (matcher Write): exit-0 stub kept at its registered path (D15).
│   ├── `posttool-restart-sendmessage.py` - PostToolUse: record successful validated restart SendMessage calls.
│   ├── `posttool-runcode-watchdog.py` - PostToolUse Hook: Cancel timeout watchdog after browser_run_code completes
│   ├── `posttool-subagent-track.py` - PostToolUse:Agent Hook: Track subagent invocations in workflow bookmark
│   ├── `posttool-todo-count.py` - PostToolUse Hook: Enforce canonical todo count immediately after TodoWrite
│   ├── `posttool-todo-sequence.py` - PostToolUse Hook: Enforce one-step-at-a-time progression in workflow checklists
│   ├── `posttool-todo-tracker.py` - PostToolUse Hook: Output checklist progress after every TodoWrite call
│   ├── `pre-commit-check.sh` - pre-commit-check.sh - Detect untracked files before commit
│   ├── `pre_slashcommand_validate.sh` - pre_slashcommand_validate.sh
│   ├── `pre_tool_use_safety.sh` - PreToolUse Safety Hook - Warn before dangerous operations
│   ├── `pretool-aggregate-check.py` - existence before allowing the orchestrator to dispatch the QA subagent in
│   ├── `pretool-attribution-pre.py` - Phase 0 of the write-time attribution journal (see hooks/lib/attribution_journal.py)
│   ├── `pretool-baseline-snapshot-preflight.py` - pretool-baseline-snapshot-preflight.py — PreToolUse hook (matcher: Agent)
│   ├── `pretool-bash-safety.sh` - PreToolUse Safety Hook - Warn or block before dangerous operations
│   ├── `pretool-bash-views-guard.py` - Parallels pretool-bash-safety.sh but focuses on views/cp-state write bypass
│   ├── `pretool-bisect-gate.sh` - pretool-bisect-gate.sh
│   ├── `pretool-block-background-tasks.py` - PreToolUse hook: block background execution on Agent/Task/Bash/SendMessage/Workflow
│   ├── `pretool-block-branch-pr-worktree.py` - Policy (user directive 2026-06-04; the verbatim user directive is preserved in
│   ├── `pretool-block-enterworktree.sh` - PreToolUse hook: Block EnterWorktree tool
│   ├── `pretool-bulk-commit-detector.py` - PreToolUse Hook: Bulk-commit detector
│   ├── `pretool-capability-gate.py` - Blocks (exit 2) any protected-workflow activation route unless the host-capability
│   ├── `pretool-claude-config-guard.py` - PreToolUse Hook: Claude config (.claude/hooks + .claude/commands) protection
│   ├── `pretool-commit-dispatch-attest.py` - Writes `<state-dir>/claude-commit-dispatch-<sid>-<nonce>.json` when, and only
│   ├── `pretool-cp-checkin.py` - cp-state file read (the write is scripts/spec-check.py's `register`)
│   ├── `pretool-cp-state-write-guard.py` - Cycle-3 slim form (2026-05-14): Bash-extractor removed — 22-form adversarial
│   ├── `pretool-do-block-subagents.py` - PreToolUse hook: block Agent/Task dispatch from the MAIN agent while a /do
│   ├── `pretool-git-privilege-guard.py` - PreToolUse Hook: Agent git-privilege guard
│   ├── `pretool-gitignore-preflight.py` - pretool-gitignore-preflight.py — PreToolUse hook (matcher: Agent)
│   ├── `pretool-grep-backtrack-guard.py` - ROOT-CAUSE BACKGROUND (verified ground truth, 2026-06-15 host OOM)
│   ├── `pretool-layer-escalation-check.sh` - pretool-layer-escalation-check.sh
│   ├── `pretool-layer-match-gate.sh` - pretool-layer-match-gate.sh
│   ├── `pretool-obligation-gate.py` - WHY THIS HOOK EXISTS:
│   ├── `pretool-orchestrator-gate.py` - PreToolUse Hook: Orchestrator Gate (Unified)
│   ├── `pretool-orchestrator-prompt-purity.py` - PreToolUse hook: Orchestrator Prompt Purity
│   ├── `pretool-overnight-hook-guard.py` - PreToolUse Hook: Overnight session file modification guard
│   ├── `pretool-overwrite-guard.py` - REGISTRATION: matcher ``Bash`` ONLY. This hook registers against no other tool
│   ├── `pretool-push-analyst-grant-guard.py` - PreToolUse (matcher Bash): exit-0 stub kept at its registered path (D15).
│   ├── `pretool-quality-gate.py` - PreToolUse Hook: Quality gate for Write/Edit operations
│   ├── `pretool-read-size-guard.py` - PreToolUse Hook: Read Size Guard
│   ├── `pretool-runcode-watchdog.py` - PreToolUse Hook: Start timeout watchdog for browser_run_code
│   ├── `pretool-spec-block-foreground-agent.py` - PreToolUse Hook: Block foreground Agent during an active /spec Interview
│   ├── `pretool-subagent-code-block.py` - Canonical enforcement: pretool-tool-policy.py + lib/policy_registry — this
│   ├── `pretool-subagent-enforce.py` - PreToolUse:Agent Hook — Contract-driven role/pipeline enforcement (G1)
│   ├── `pretool-todo-validate.py` - PreToolUse Hook: Validate TodoWrite input BEFORE execution
│   ├── `pretool-tool-policy.py` - tool-policy.v1.json for all subagents
│   ├── `pretool-workflow-gate.py` - PreToolUse Hook: Require TodoWrite/TodoRead acknowledgment before other tools
│   ├── `pretool-worktree-guard.sh` - PreToolUse hook: Detect stale agent worktrees before ANY tool call
│   ├── `pretool-wrapper-userintent.py` - fix-4 (Cycle-2, spec-20260604-204954 §7.4). The /stop slash command releases
│   ├── `pretool-write-guard.sh` - PreToolUse Hook - Block Write tool from overwriting existing files
│   ├── `project-settings-template.json` - JSON config: $schema, comment, comment_usage, hooks, permissions
│   ├── `prompt-workflow.py` - UserPromptSubmit Hook: Checklist Injection for Slash Commands
│   ├── `protection-status.sh` - protection-status.sh - Display protection status for all git repositories
│   ├── `pull.sh` - pull.sh - Executable version of /pull command
│   ├── `push.sh` - push.sh - Executable version of /push command
│   ├── `QUICKSTART.md` - Quick Start — the hooks layer
│   ├── `README-TODO-INJECTION.md` - Global Todo Injection Hook
│   ├── `sentinel-lint.sh` - sentinel-lint.sh - Guards the dev-registry sentinel anchor in orchestrator files
│   ├── `session-git-init.sh` - Ensure Git Repository Hook for Claude Code
│   ├── `session-gitignore-propagate.sh` - SessionStart hook: append missing standard harness gitignore rules to project repo
│   ├── `session-info.sh` - s-info.sh — SessionStart: display environment info + tool quick reference
│   ├── `session-promote-hook.sh` - Description: SessionStart hook that promotes a cold session back to ramdisk.
│   ├── `session-scratch-init.sh` - session-scratch-init.sh — SessionStart hook (Scratch Lifecycle Contract
│   ├── `session-tmpfs-banner.sh` - session-tmpfs-banner.sh — SessionStart hook (6th in the SessionStart hooks block).
│   ├── `session_start.sh` - SessionStart Hook - Display working environment info
│   ├── `sessionend-scratch-sweep.sh` - sessionend-scratch-sweep.sh — SessionEnd hook (Scratch Lifecycle Contract
│   ├── `start-fswatch-all.sh` - start-fswatch-all.sh - Start fswatch monitoring for all important repositories
│   ├── `stop-cleanup-allowlist.sh` - Stop Hook: reap every /allow grant the reader rejects at turn end.
│   ├── `stop-completion-gate.py` - blocked compliant /dev Stops with GATE_ERROR and its only release was a
│   ├── `stop-do-report-gate.py` - A /do session mints a task-id sidecar (<state dir>/claude-do-task-<sid>.json) at
│   ├── `stop-obligation-gate.py` - It re-validated, at the orchestrating session's Stop, the json artifacts its
│   ├── `stop-overnight-timelock.py` - Stop Hook: Block conversation termination until overnight end-time
│   ├── `stop-spec-coverage-enforce.py` - Stop Hook: Block spec agent from exiting with < 100% monolith coverage
│   ├── `stop-workflow-coordinator.py` - LANE-B (20260808-035658) M4/M7: the registered Stop hook, running the four former Stop
│   ├── `stop.sh` - stop.sh - wrapper for /stop slash command
│   ├── `subagent-stop-diff-check.sh` - SubagentStop hook: flag large diffs without minimum-diff justification
│   ├── `subagent-stop-guard-integrity.sh` - subagent-stop-guard-integrity.sh
│   ├── `subagentstop-artifact-contract-enforce.py` - Ports the /close "Artifact schema gate" (commands/close.md §"Artifact schema gate" — the
│   ├── `subagentstop-codex-enforce.py` - Activation logic:
│   ├── `subagentstop-cp-enforce.py` - Description: SubagentStop hook for spec checkpoint enforcement (W6).
│   ├── `subagentstop-e2e-enforce.py` - Activation logic:
│   ├── `subagentstop-restart-track.py` - SubagentStop: persist response evidence for a /restart-resumed agent.
│   ├── `userprompt-bulk-commit-capability.py` - human prompt, NOT from an LLM-emitted Bash command
│   ├── `userprompt-consent-allowlist.sh` - UserPromptSubmit Hook: parse `/allow <pattern>` and write a single-use
│   ├── `userprompt-doc-sync-check.py` - UserPromptSubmit Hook: Periodic file deletion detection for doc-sync
│   ├── `userprompt-restart-authorize.py` - UserPromptSubmit: mint a session-bound capability for a human /restart invocation.
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
│   ├── `dev-report.v1.json` - Per-task dev implementation report. Read by QA, PM RETRO, and the closeout aggregator.
│   ├── `dev-report.v2.json` - Per-task dev implementation report, v2: matches the REAL nested producer template (agents/dev.md:590-674 — nested dev.status, top-level baseline keys) instead of v1's flat shape. Required baseline_head_sha/baseline_dirty_snapshot mirror the live producer checks at scripts/aggregate-dev-report.py:529-546 (commit inventory #71/#72, close #20/#22; empty string is legal for both — unborn repo / clean tree). The AC-deviation sub-shape is copied from its canonical machine-shape definition at scripts/resolve-dev-artifact-chain.py:80-130. lane/lane_set follow docs/reference/close-commit-zero-failure-mechanism-20260928.md §1.1(e)/§1.2: lane_set is required non-null when lane is a string; lane-membership (lane ∈ lane_set) is NOT expressible in Draft7 and is the later G2 echo check, deliberately not faked here. Authority: design §1.6 (schema v2 cutover).
│   ├── `do-report.v1.json` - Lightweight /do completion report. The /do main agent writes the whole report (commands/do.md Step 5) before session stop (enforced by hooks/stop-do-report-gate.py). Read by /close (do-report path) and /commit.
│   ├── `graphify-focused-subgraph.v1.json` - Task-scoped subgraph extracted from the global Graphify knowledge graph, focused on files in the BA blast-radius-map. Written to .claude/dev-registry/{task_id}/graphify/focused-subgraph.json by graphify-enrich.py.
│   ├── `graphify-prequery.v1.json` - Step 1.5 output from graphify-query.py. Contains structural_context extracted from the global Graphify cache before BA analysis. Status field drives BA behaviour: ok/degraded proceed, unavailable/skipped silently bypass.
│   ├── `graphify-run.v1.json` - Step 7.5 run record, written by graphify-enrich.py on every path: its status, the cache refresh, the focused subgraph extraction, and the context fingerprint /dev-overnight Step 11g compares. graphify never writes the context.
│   ├── `obligation.v1.json` - Validates the JSON payload of the <obligation v="1"> block per docs/reference/close-commit-zero-failure-mechanism-20260928.md §1.2 (the XML wrapper itself is the S2 grammar library's concern, not this schema's). additionalProperties false at the top level: G1's job is shape-rejection of drifted blocks (design M5/M7/M28); cross-version tolerance is carried by the wrapper's v attribute (M29), not by an open v1 object. Path fields (artifacts[].path, expected_absent[]) are repo-relative and traversal-free (must not start with '/', must not contain '..'); G1 re-checks at dispatch — the schema encodes the invariant so a registered grammar exists (G1 check 2). The null-task_id gate's expressible half is encoded (profile outside {ad_hoc, commit-bulk, commit-qa} forces a string task_id); commit-qa's context-dependence (bulk-context null vs task-scoped string) is enforced by G1 later, not by this schema. lane-membership (lane ∈ lane_set) is the later G2 echo check, not expressible in Draft7.
│   ├── `owned-edits-ledger.v1.json` - Machine-readable definition of the owned-edits ledger a dev-report must carry so that scripts/stage-owned-hunks.py can stage this cycle's owned hunks. DERIVED FROM THE CONSUMER'S CODE, not from agent prose; see x-consumer for the digest it is derived from and x-citation-policy for why nothing here cites a line number. Plus the snapshot-materialization rule in agents/changelog-analyst.md, locatable by searching for '2. Snapshot materialization (REQUIRED', which is the only place the report-level pre_edit_snapshots map is turned into the --snapshot file the consumer reads. Where prose and code disagree, the code governs; see x-prose-code-disagreements below.
│   ├── `paseo-dossier.v1.json` - Structured sidecar validated by scripts/paseo-daemon-ledger.py dossier-validate. Fail-closed: a dossier missing any required F12 field, or carrying a malformed seven-field decision-journal record, must never become a committed generation. The dossier is an index and checkpoint ONLY — authoritative evidence remains the session transcript and hash-verified artifact files.
│   ├── `producer-question.v1.json` - Written by a ba or dev producer, in place of its report, when it needs one owner decision that the request, the code and a sensible default cannot settle: docs/dev/producer-question-<task_id>-<role>.json. The orchestrator relays it with one AskUserQuestion (options become the dialog's options, default the recommended one) and re-dispatches the same role. The subagentstop artifact-contract hook checks task_id and role against the dispatch's obligation and that default is one of the option labels, which JSON Schema cannot express.
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
│   │   ├── `attribution_adjudicator.py` - Phase D cutover (docs/reference/attribution-journal-cutover-flip-plan-20261003.md,
│   │   ├── `attribution_aggregate_view.py` - Emits the canonical dev-report document shape that /close and /commit
│   │   ├── `candidate_tree.py` - An acceptance harness usually has to evaluate its criterion against neither the
│   │   ├── `make_sbom.py` - The SBOM is built from the archive's real contents, not from the source
│   │   ├── `release_membership.py` - Single source of truth shared by every consumer, so the archive builder, the
│   │   ├── `score_log.py` - ``scripts/score-update.sh`` (the log's writer) and ``scripts/score-inject.sh`` read
│   │   ├── `session_index.py` - A repository has exactly one shared index file (``$GIT_DIR/index``). Every session
│   │   ├── `sibling_loader.py` - ``scripts/close-route-select.py``, ``scripts/late-repair-controller.py`` and
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
│   │   ├── `spec_verify_parsers.py` - Authoritative grammar: /root/docs/dev/specs/MONOLITH-WRITING-GUIDE.md R6.6
│   │   └── `spec_verify_summary.py` - Lives alongside `spec_verify_parsers.py` as a sibling sidecar because
│   ├── todo/
│   │   ├── `clean.py` - Preloaded TodoList for /clean workflow
│   │   ├── `close.py` - Three user-visible TodoSteps (flat-integer per agents/style-inspector.md
│   │   ├── `code-review.py` - Python script
│   │   ├── `deep-search.py` - Python script
│   │   ├── `dev-command.py` - This todo script generates workflow steps for the BA-delegated dev-command workflow
│   │   ├── `dev-overnight.py` - Preloaded TodoList for /dev-overnight workflow
│   │   ├── `dev.py` - Preloaded TodoList for /dev workflow
│   │   ├── `do.py` - Injects the 5-step /do workflow checklist via hook-todo-injection
│   │   ├── `doc-gen.py` - Python script
│   │   ├── `explain-code.py` - Python script
│   │   ├── `file-analyze.py` - Preloaded TodoList for /file-analyze workflow
│   │   ├── `optimize.py` - Python script
│   │   ├── `playwright-helper.py` - Python script
│   │   ├── `quick-prototype.py` - Preloaded TodoList for /quick-prototype workflow
│   │   ├── `redev.py` - Preloaded TodoList for /redev workflow. Delegates to dev.py (single source of truth).
│   │   ├── `refactor.py` - Python script
│   │   ├── `reflect-search.py` - Preloaded TodoList for /reflect-search workflow
│   │   ├── `research-deep.py` - Python script
│   │   ├── `security-check.py` - Python script
│   │   ├── `site-navigate.py` - Python script
│   │   ├── `spec.py` - Mirrors the ask.py structure in the knowledge-system scripts/todo directory
│   │   └── `test.py` - Preloaded TodoList for /test workflow
│   ├── `adjudicate-attribution-staging.py` - CLI: journal-based three-way staging adjudicator (read-only unless --capture-dispatch-baselines-into or --escalation-store is given; see scripts/lib/attribution_adjudicator.py).
│   ├── `aggregate-dev-report.py` - Scans docs/dev/ for per-worker shard dev-reports matching a given task-id,
│   ├── `aggregate-permissions.py` - Usage: aggregate-permissions.py <qa-glob-or-dir> [pipelines.json]
│   ├── `analyze-folder-history.sh` - Description: Analyze Git history for folder to discover file creation patterns
│   ├── `analyze-git-edge-cases.sh` - Description: Analyze git history for edge cases from bug fix commits
│   ├── `apply-permissions.sh` - apply-permissions.sh — merge aggregated permissions JSON list into settings.json
│   ├── `attribution-aggregate-view.py` - CLI: journal-backed canonical aggregate view (read-only unless --escalation-store is given; see scripts/lib/attribution_aggregate_view.py).
│   ├── `blast-radius-tool.py` - Two phases:
│   ├── `bootstrap` - bootstrap file
│   ├── `break-overnight-lock.py` - Backdates end_time on every active overnight-state-*.json so
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
│   ├── `check-security-hook-drift.sh` - Description: Audit always-on security-critical hook files against a cycle baseline SHA
│   ├── `checkpoint-prune.sh` - checkpoint-prune.sh — trim refs/checkpoints/* to the most recent N commits
│   ├── `close-report-append.py` - Description: Deterministic read-append-reread-verify helper for the
│   ├── `close-route-select.py` - Without ``--late-repair`` this is a pass-through: it resolves the artifact
│   ├── `close-scoring-decide.py` - Description: Decide which close_success_* event /close should issue based on
│   ├── `commit.sh` - Description: Discoverable canonical entrypoint for commands/dev-overnight.md's
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
│   ├── `gen-test-baseline.py` - Usage:
│   ├── `generate-folder-index.sh` - Description: Generate INDEX.md for folder (inventory of contents)
│   ├── `generate-folder-readme.sh` - Description: Generate README.md for folder (purpose and organization rules)
│   ├── `generate-hero-status.py` - Description: One source of truth emits THREE marker-delimited canonical regions -- the
│   ├── `graphify-enrich.py` - graphify-enrich.py — pre-DEV focused subgraph extractor (runs between Step 7 and Step 8)
│   ├── `graphify-maintain.py` - graphify-maintain.py — Global Graphify cache lifecycle manager (REAL CLI)
│   ├── `graphify-query.py` - graphify-query.py — deterministic pre-BA graph hydrator (runs between Step 1 and Step 2)
│   ├── `graphify_lib.py` - graphify_lib.py — shared library for Graphify knowledge-graph integration
│   ├── `install-checkpoint-refspec.sh` - install-checkpoint-refspec.sh — idempotently add refs/checkpoints/* to
│   ├── `install-git-keystone.sh` - install-git-keystone.sh — wire the git-native reference-transaction keystone
│   ├── `iterate-failed-pipelines.py` - Reads pipelines JSON path; outputs iteration plan JSON to stdout. The orchestrator
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
│   ├── `refine-context.sh` - STUB: the QA-fail loop re-dispatches dev with the QA report path; no context is merged any more.
│   ├── `regen-index-dirs.py` - hand-written prose outside the generated stats+tree block), then regenerate the
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
│   ├── `spec-check.py` - Subcommands: check-in, register, checkpoints, mark, waive, status, check-out, unlock
│   ├── `spec-write.py` - Every write of a spec file runs through this script: /spec's own writes (the
│   ├── `stage-owned-hunks.py` - Stages ONLY this cycle's owned hunks within a single already-authorized file,
│   ├── `step7-spec-update.py` - Step 8 (Spec-update dispatch) reference harness — task 20260524-205206 iter-2
│   ├── `test` - test file
│   ├── `update-gitignore.sh` - update-gitignore.sh - Auto-update .gitignore with project-specific rules
│   ├── `verify-attribution-chain.py` - Folds each file's events across ALL session journals into a hash chain and
│   ├── `verify-claims-extended.sh` - Description: Extended headline-claims gate. Binds the slash-command count and the
│   ├── `verify-claims.sh` - Description: Self-verifying headline-claims gate. Runs ALL THREE hero-provenance audits in
│   ├── `verify-hero-provenance.py` - Description: Re-runs the demo, normalizes both outputs and byte-diffs them; verifies raw
│   ├── `verify-release-manifest.sh` - Description: Verify a PUBLISHED release artifact end-to-end, WITHOUT rebuilding it.
│   ├── `write-bulk-commit-sentinel.py` - Invoked from commands/commit.md Step 5 (BULK=true) to authorize the
│   ├── `write-codex-enforce.sh` - Writes codex-enforce.json into the dev-registry for the given session.
│   ├── `write-commit-grant.py` - Invoked from `commands/commit.md` Step 5 (non-bulk mode) to author a
│   ├── `write-e2e-enforce.sh` - Writes e2e-enforce.json into the dev-registry for the given session.
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
│   │   ├── `report-schema.json` - Schema for the ui-specialist subagent's final JSON report. Implements spec-20260426-080555 section 5.5 (6 channels) + 5.11 (hard_defect vs taste_heuristic) + 5.15 (skill outputs) + double-defense severity hard-cap on aesthetic_findings.
│   │   ├── `review-phases.yml` - YAML config: phase_order, phases
│   │   └── `rule-map.json` - JSON config: $schema_version, meta, rules
│   ├── ui-state-matrix/
│   │   └── `SKILL.md` - Verify presence of 7 interactive states (default / hover / focus / active / disabled / loading / error / success) on key interactive elements. Returns deterministic state.* findings + state_coverage_pct + not_applicable[]. Use during ui-specialist Phase 4 (Interactive Element Visual Testing).
│   └── ui-token-conformance/
│       └── `SKILL.md` - Conditional capability — measure design-token conformance (color/spacing/typography) of computed CSS values against a project's declared token source (DTCG / tailwind.config.js / theme.ts). If no token source is detected, emit capability_unavailable to unknowns and DO NOT raise findings on guesses. Use during ui-specialist Phase 5 (Aesthetic).
├── templates/
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
│   │   ├── `shparse.py` - dependency beyond the standard library
│   │   ├── `shscan.py` - Words are evaluated into the same templates as Python values (variables by
│   │   ├── `static_half.py` - `derive(tree)` reads one harness tree and returns every record the static
│   │   ├── `test_check.py` - Each test builds a small harness-shaped tree, derives the static half on it and
│   │   ├── `test_rule2.py` - Each test builds a small harness-shaped tree, derives the static half on it and runs the check's
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
│   ├── replay/
│   │   ├── drivers/
│   │   ├── `__main__.py` - `python -m tests.replay ...`: see cli.py.
│   │   ├── `agents.py` - A pipeline driver renders a dispatch prompt from the tree under test (its
│   │   ├── `cli.py` - python -m tests.replay build --tree T --sandbox SB
│   │   ├── `cmdtext.py` - Drivers never hard-code a block's text: they take it, at run time, from the
│   │   ├── `differential.py` - A reader decides on an artifact when re-running its recorded invocation with
│   │   ├── `hookrun.py` - Selection follows the planning kit's runhook.py: a matcher that is empty or "*"
│   │   ├── `inner.py` - cli.py starts it as `python -m replay.inner <config.json>` from the sandbox's
│   │   ├── `norm.py` - A replay's own values (session ids, agent ids, tool-use ids, task ids, lanes,
│   │   ├── `pipeline.py` - An Orchestrator plays the main agent of one typed command, following the
│   │   ├── `replay.py` - A driver gets a Replay and works through Sessions and Actors (the main agent,
│   │   ├── `roles.py` - Each helper returns an Act.work callable, work(sub, brief, player) -> content,
│   │   ├── `sandbox.py` - One scratch root holds everything a replay touches:
│   │   ├── `schemagen.py` - A simulated subagent writes each JSON artifact its obligation declares from the
│   │   └── `trace.py` - The replay runs under `strace -f --seccomp-bpf -z -y` tracing opens (with
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
│   ├── `test_ac_deviation_fanout_consumer.py` - records and the lifecycle presentation of ``pass_with_exceptions``
│   ├── `test_ac_deviation_record_chain.py` - A dev report that legitimately records an acceptance-criteria deviation is
│   ├── `test_aggregate_dev_report.py` - Unit tests for scripts/aggregate-dev-report.py
│   ├── `test_aggregate_dev_report_superseded_rounds.py` - aggregate dev-report's ownership-completeness check over a multi-lane,
│   ├── `test_apply_permissions.py` - /dev and /dev-command apply the permissions QA validated with the line their permission step
│   ├── `test_artifact_graph.py` - The check (tests/artifact_graph/check.py) replays every driver under
│   ├── `test_bash_write_targets_verb_narrowing.py` - The library used to read a word that merely begins `cp-`/`mv-` (a checkpoint id such as `cp-01`, a
│   ├── `test_bootstrap_init.py` - Every case runs in its own temporary clone of this repository, synced to the
│   ├── `test_candidate_tree.py` - Every test builds its own throwaway git repository. None of them reads this
│   ├── `test_changelog_analyst_declaration_categories.py` - `agents/changelog-analyst.md` decides what a cycle commits by reading declaration
│   ├── `test_changelog_analyst_files_landed_whole_toctou.py` - `files_landed_whole` TOCTOU-safe stage-then-verify sequence (currently at
│   ├── `test_changelog_analyst_required_to_ship_sourcing.py` - unobtainable declaration must not be silently read as an empty one
│   ├── `test_checkpoint_provenance.py` - These modes are DORMANT: no command, agent definition, or hook invokes them by
│   ├── `test_clean_orchestrator_merge.py` - clean-merge-reports reads the three inspector reports of the request the Step 3 context
│   ├── `test_close_report_append.py` - failure semantics (round-7 CRITICAL fix, ticket dev-20260919-135733)
│   ├── `test_codex_workflow_gate.py` - Regression tests for Codex-native workflow-plan compatibility.
│   ├── `test_commit_multi_repo_plan.py` - Python script
│   ├── `test_commit_sh_reachability.py` - commands/dev-overnight.md:1561 previously called a bare, unqualified
│   ├── `test_completeness_channel_invariant.py` - One defect with a producer half and a consumer half:
│   ├── `test_completeness_span_accounting.py` - halves on one code path
│   ├── `test_conftest_hermetic.py` - conftest.py removes CLAUDE_PROJECT_DIR, PASEO_CONFIG_DIR, CLAUDE_HOME, CODEX_HOME,
│   ├── `test_declared_vocab_readers.py` - (P1b row 19 rule 7): the chain resolver's disclosed-exception
│   ├── `test_dev_artifact_chain_consumer_contracts.py` - Contract tests for shared /dev artifact-chain consumers.
│   ├── `test_dev_todo_accounting.py` - Python script
│   ├── `test_empty_old_string_diagnosis.py` - A real cycle emitted twenty-one ledger entries whose `old` was the empty string
│   ├── `test_git_auto_push_opt_in.py` - Guards D1: nothing pushes outside /push unless GIT_AUTO_PUSH=1. Four code paths
│   ├── `test_git_clean_guard_vectors.py` - The pre-clean WIP snapshot guard (task dev-20260719-150041-c, lane r03-c) is
│   ├── `test_graphify_enrich_outputs.py` - The script reads the context file it is given and never writes it; it writes the run
│   ├── `test_graphify_scripts.py` - tests/test_graphify_scripts.py — smoke tests for scripts/graphify_lib.py
│   ├── `test_graphify_workflow_contract.py` - tests/test_graphify_workflow_contract.py — contract tests for graphify agent registration
│   ├── `test_hero_advance_cross_check.py` - tools/demo/audit.mjs measures a line's rendered right edge on a fixed monospace grid, using
│   ├── `test_interruption_signals.py` - Every banner asserted here was measured in the real transcript corpus under
│   ├── `test_landing.py` - render-settings land, run from hooks/auto-commit.sh), migrate's push exclusion and the settings
│   ├── `test_late_repair_driftfree_effective_state.py` - scripts/late-repair-controller.py's ``resolve_effective_report_state`` is the
│   ├── `test_late_repair_route.py` - Covers AC-7..AC-11, AC-13, AC-14 (spec-20260907-115508-lawful-commit-channel.md,
│   ├── `test_no_artificial_lifecycle_ceremony.py` - Prevent host metadata ceremonies from becoming ordinary lifecycle gates.
│   ├── `test_overnight_guard_in_place_git.py` - Defect (2026-08-09): `hooks/pretool-overnight-hook-guard.py` blocked EVERY git
│   ├── `test_overnight_loop_tz.py` - Verifies the overnight loop hook compares end_time correctly against the
│   ├── `test_parent_cycle_claimant_reader.py` - THE DEFECT.  Admission to a cycle's ownership-completeness claimant set was
│   ├── `test_paseo_daemon_ledger.py` - MANDATORY pytest facade for lane 20260828-112025-b: collects EVERY test
│   ├── `test_paseo_daemon_timers.py` - scripts/paseo-daemon-timers.py (task 20260926-111239)
│   ├── `test_paseo_usage_read.py` - MANDATORY pytest facade for lane 20260828-112025-b: collects EVERY test
│   ├── `test_private_literal_rule.py` - pre-commit hook hooks/git-hooks/pre-commit
│   ├── `test_prompt_workflow_injection_cadence.py` - The defect: ``build_overnight_continuation`` emitted ONE payload at ONE cadence
│   ├── `test_prompt_workflow_liveness_tz.py` - Two defects, both reproduced before this suite was written:
│   ├── `test_public_core_residue_gate.py` - These are the discriminating controls for the "Make CI FAIL (not advisory) on
│   ├── `test_refusal_record_consumers.py` - This is the module named BY NAME as `check.cli_run.harness` by AC12 and AC14 of
│   ├── `test_release_pipeline_contract.py` - verifier
│   ├── `test_resolve_dev_artifact_chain.py` - Focused tests for the read-only /dev artifact-chain resolver.
│   ├── `test_resolve_spec_artifacts.py` - resolver) + the static centralization lint (AC-B4 cases 1-12, task 20260530-092123)
│   ├── `test_restart_command.py` - End-to-end unit coverage for the human-only /restart recovery protocol.
│   ├── `test_score_log.py` - scripts/score-update.sh and scripts/score-inject.sh both call read_lines in place
│   ├── `test_settings_filter.py` - applied layers, the machine-form renderer, the doctor and pre-commit checks, and the owner
│   ├── `test_settings_load.py` - take its verdict which no other test runs: the claude_home probes, installer.py's plan, and the two
│   ├── `test_spec_check_agent_id_guard.py` - Lane b of task 20260921-134709. Self-contained and subprocess based: one scratch
│   ├── `test_spec_check_closed_slot.py` - task 20260921-134709)
│   ├── `test_spec_check_concurrent_marking.py` - also when hooks/pretool-cp-checkin.py runs it on a subagent's Read (harness backlog #97)
│   ├── `test_spec_update_command_contracts.py` - Contracts for the live ``/spec-update`` command policy and its history entry.
│   ├── `test_spec_verify.py` - The overlap and uniqueness rules do not count the lines the split rules route into
│   ├── `test_spec_write.py` - Each test runs the script as a subprocess against a throw-away project under
│   ├── `test_specialist_yield.py` - Tests use a tmp dir for the yield log and the bundled production policy file
│   ├── `test_stage_owned_hunks_boundary.py` - content-anchor-retry boundary/coordinate-space defect (task 20260912-015952)
│   ├── `test_subagentstop_e2e_enforce.py` - A QA dispatch that carries an obligation is judged on exactly the qa-report
│   ├── `test_todo_md_sync.py` - Regression tests for the session-start todo/Markdown drift detector.
│   ├── `test_tool_policy_note_fail_closed.py` - hooks/pretool-tool-policy.py refuses a Bash write target with exit 2 and then
│   ├── `test_verify_claims_tracked_form.py` - On an initialised home the claude-settings filter leaves the machine form in the
│   ├── `test_write_qa_mode.py` - Each QA dispatch's obligation now declares the report it owes, so no qa_mode
│   ├── `TESTING.md` - Test Topology & Runner Map (authoritative)
│   └── `verify-stop-spec-session-isolation.sh` - QA verification harness for stop-spec-coverage-enforce.py session isolation fix.
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