# dot-claude

<!-- AUTO:index-stats -->
*Last updated: 2026-10-06T02:29:52Z*
**Total entries**: 730
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
│   ├── `graphify.md` - Graphify enrichment subagent. Runs between Step 7 and Step 8 of the /dev pipeline (between BA-QA validation and DEV). Performs incremental Graphify cache update, extracts focused subgraph from BA blast-radius-map, patches context-<ts>.json with graph_context field, writes per-task artifacts to .claude/dev-registry/<task_id>/graphify/. Pure infrastructure agent — does NOT analyze requirements, make implementation decisions, write code, or interpret graph data for DEV.
│   ├── `merge-analyst.md` - Pre-merge analyst subagent. Inspects branch divergence, diff stat, conflict markers, and overnight-state consistency; writes a nonce-keyed merge-analyst grant (60s expiry) to /tmp/agentic-commit/merge-analyst/. Dispatched exclusively by /merge.
│   ├── `pm.md` - Test plan manager for overnight exploration with 3 invocation modes: PLAN (build test plan via browser exploration), TRIAGE (prioritize issues from specialist reports), RETRO (retrospective analysis and cross-cycle continuity). Uses Playwright to navigate the running app in PLAN mode before writing the test plan.
│   ├── `product-owner.md` - Product-level analysis specialist for overnight exploration. Examines logical consistency, feature completeness, user flows, missing features, and business logic bugs. Returns structured JSON report.
│   ├── `prompt-inspector.md` - Prompt optimization inspector. Detects verbose non-functional content in command/agent documentation following 'rules not stories' principle. Returns structured JSON report with verbosity violations.
│   ├── `pull-analyst.md` - Post-pull advisory analyst subagent. Reads the new-commits range after a successful git pull --rebase and produces a structured semantic risk summary. Writes no grant and blocks nothing. Dispatched exclusively by /pull when HEAD actually changed.
│   ├── `push-analyst.md` - Pre-push analyst subagent. Inspects the commits-to-push range for sensitive files, divergence, and branch protection violations; writes a nonce-keyed push-analyst grant to /tmp/agentic-commit/push-analyst/. Dispatched exclusively by /push.
│   ├── `qa.md` - Quality assurance specialist for verification tasks. Receives implementation report from dev subagent, validates against success criteria, runs verification scripts, identifies issues. Returns structured verification report with pass/fail status.
│   ├── `rule-inspector.md` - Folder rule discovery agent. Analyzes Git history to discover file creation patterns, extracts folder organization rules, generates INDEX.md and README.md documentation. Returns structured JSON with discovered rules.
│   ├── `spec.md` - Three-phase spec subagent. Phase 0 = read spec, decide which agents need views (free judgment). Phase 1 = content-block extraction from full monolith (verbatim byte-slices, no section pre-filtering). Phase 2 = Gawande-style checkpoint generation. Invoked by /spec command with monolith path.
│   ├── `style-inspector.md` - Development standards auditor. Enforces /dev quality standards: no hardcoding, naming conventions, venv usage, step numbering, language, script merging, documentation conciseness. Returns structured JSON report with violations.
│   ├── `test-executor.md` - Execution specialist for test infrastructure. Executes script-based and AI instruction-based tests. Returns structured execution report with results and recommendations.
│   ├── `test-validator.md` - Validation specialist for test infrastructure. Validates test syntax, dependencies, and quality before execution. Returns structured validation report.
│   ├── `test-writer.md` - Generate pytest skeleton tests from BA-produced acceptance-criteria-<task_id>.json with pytest.fail("TEST_INCOMPLETE:...") hard-stops; manage tests/generated/manifest.json with UPDATE vs CREATE logic keyed on ac_uid hashes. Triggered by /dev when complexity_tier >= STANDARD or any tier with risk_level = high (per spec-20260518-225715 §5.2).
│   ├── `ui-specialist.md` - UI/UX review specialist for overnight exploration. Evaluates visual design quality, aesthetic beauty, design system adherence, styling consistency, responsive design, and component quality. Returns structured JSON report with beauty score and design quality assessment. Accessibility checks are advisory.
│   └── `user.md` - End-user simulation specialist for overnight exploration. Tests actual usage scenarios, checks if things work as expected, identifies UX friction, broken flows, and confusing behavior. Returns structured JSON report.
├── commands/
│   ├── `allow.md` - Single-use break-glass for a declared grant-aware safety hook; it never overrides a settings DENY. Forms — /allow <command...> (literal, upgraded to regex only when it contains true regex metacharacters), /allow --tool <literal> (always literal, regex off), or /allow re:<anchored-regex> (explicit regex, must be anchored). Bare /allow with no argument is the owner-authorized match-all selector, still single-use and TTL-bounded; every explicit selector is refuse-by-default when no narrow command is derivable. A literal selector matches as a POSITIONAL PREFIX of the argument tokens, not a substring. When the head token is git, repo-retargeting global options (-C, --git-dir, --work-tree, --namespace) are skipped so a short selector reaches the canonical `git -C <dir> <verb>` shape; -c / --config-env / --exec-path are never skipped and fail closed. Trailing tokens become an audit-log comment. Sentinel TTL 300s, consumed on any terminal result.
│   ├── `checkpoint.md` - Checkpoint Command
│   ├── `clean.md` - Aggressive project cleanup - normalize docs structure, archive everything, delete one-time scripts/tests. Pass --codex to enable adversarial codex consultation on cleanliness-inspector and style-inspector; default is self-review only.
│   ├── `close.md` - Close the current dev cycle (agent infers task-id from conversation). QA evaluates Workflow Integrity bullets and returns CLOSE YES/with-disclosures. Pass --codex to enable multi-round QA-codex debate; default is QA-only single-round assessment. --force is DEPRECATED -- a no-op alias of the normal path (audit-logged, skips nothing). Pass --auto to discover and sequentially close every close_pending parent (see `--auto mode` below).
│   ├── `codex.md` - Delegate a task to OpenAI Codex CLI (gpt-5.6-sol, xhigh reasoning) for a second opinion or parallel coding
│   ├── `commit.md` - Commit session changes via changelog-analyst subagent
│   ├── `dev-command.md` - Enhanced development workflow with BA subagent delegation, command development best practices, Three-Party Architecture, and comprehensive automation patterns
│   ├── `dev-overnight.md` - Autonomous overnight development loop - continuously explores codebase, finds issues, fixes them, and repeats until end-time
│   ├── `dev.md` - Orchestrated development workflow with BA subagent delegation, parallel agent execution, and iterative QA verification. Pass --codex to enable adversarial codex consultation on each subagent's draft; default is self-review only.
│   ├── `do.md` - Allow main agent to bypass orchestrator-gate restrictions for this turn (subagent-only operations become directly allowed). Auto-clears at stop.
│   ├── `merge.md` - Merge a branch into the default branch, on either a linked (registered_worktree) worktree or an in_place one (the main checkout -- see commands/dev-overnight.md's isolation_kind vocabulary). On a linked worktree, the agent infers the branch from active overnight state, auto-removes the worktree, deletes the merged branch, and removes the overnight-state file. In_place, the agent merges the current (or explicit) branch directly in the main root, requires a clean tree first, and keeps the branch afterward. Bare /merge typical; explicit /merge <branch> overrides.
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
│   │   ├── `abandoned-cycles-20260905.md` - Abandoned cycles — terminal determination
│   │   ├── `attribution-journal-consumer-cutover-20261004.md` - Attribution-journal consumer cutover: APPLIED (task 20261004-001927)
│   │   ├── `attribution-journal-cutover-flip-plan-20261003.md` - Attribution-journal cutover: FLIP PLAN (Phase D, plan only)
│   │   ├── `attribution-journal-phase0-facility.md` - Write-time attribution journal — Phase 0 facility notes
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
│   │   ├── `dev-command-20261003-020648-takeover-record.md` - Takeover record — cycle `dev-command-20261003-020648` over interrupted `dev-command-20261002-170011`
│   │   ├── `fswatch-quickref.md` - FSWatch Quick Reference Card
│   │   ├── `generated-tests-policy.md` - `tests/generated/` policy — tracked but ignored, on purpose
│   │   ├── `git-fswatch.md` - Git File Watcher (fswatch) Documentation
│   │   ├── `graphify-integration.md` - Graphify Knowledge Graph Integration
│   │   ├── `harness-defects-20260906-controller.md` - 控制器实测缺陷记录 — 2026-09-06
│   │   ├── `harness-fix-status-20260905.md` - Harness fix status — R1..R20 of `spec-20260904-harness-fixes.md`
│   │   ├── `harness-gaps-found-20261005.md` - Harness gaps found during the 2026-10-05 tree-to-zero campaign
│   │   ├── `harness-issues-backlog.md` - 待下次 spec 处理的 harness 问题清单（当前有 harness 修复在 worktree 跑，新问题只记录不并行修）
│   │   ├── `infeasibility-without-execution-20261006.md` - An infeasibility judgment that was never executed is a hypothesis, not a finding
│   │   ├── `install-compatibility-matrix.md` - Install compatibility matrix
│   │   ├── `lane-pol-catchup-plan-20260808-035658-lanepolcatchup.md` - LANE-POL Catch-Up Plan — origin/master → fix/dev-fanout-gatekeeper-20260717
│   │   ├── `launch-plan.md` - Launch Plan — ROI-ranked channels, gated on recorded evidence
│   │   ├── `lock-file-handling.md` - Git Lock File Handling
│   │   ├── `master-origin-reconciliation-gap-20261005.md` - No history-preserving reconciliation path exists between local master and diverged origin/master
│   │   ├── `mat-doc10-writer-order.v2.json` - JSON config: schema, contract_id, spec_id, lane_id, published_by_task_id
│   │   ├── `monolith-split-plan.md` - Monolith Split Plan (Plan-of-Record)
│   │   ├── `MORNING-20260907.md` - 晨间交接 — 2026-09-07
│   │   ├── `open-findings-from-read-only-cycles-20261005.md` - Open findings from read-only cycles — extracted 2026-10-05
│   │   ├── `overnight-cycle-20260809-013317-shared-file-attribution-20260914.md` - Attribution of unattributed content in four shared files, cycle 20260809-013317
│   │   ├── `overnight-reference.md` - Overnight reference (maintainer-facing)
│   │   ├── `overnight-worktree-20260810-test-gaps-20261005.md` - Overnight 20260810 worktree test landing: diagnosis of 22 files
│   │   ├── `overnight-worktree-test-gaps-20261005.md` - Overnight 20260809 worktree test landing: diagnosis of 15 failures
│   │   ├── `overwrite-prohibition.md` - Prohibition on wholesale replacement of an existing file
│   │   ├── `paseo-daemon-caller-id-rollout-20261004.md` - `--caller-id` enforcement: immediate rollout, no deploy step, doc gap
│   │   ├── `paseo-daemon-concurrent-staging-triple-repro-20260904-181435-20260914.md` - Triple, independent reproduction of the shared-file concurrent-staging defect
│   │   ├── `paseo-daemon-shared-file-attribution-20260913.md` - Attribution of unattributed content in the three paseo-daemon shared files
│   │   ├── `paseo-daemon-teachings-20260910.md` - paseo-daemon 控制器教训合并与运行契约（2026-09-10）
│   │   ├── `positioning.md` - Positioning
│   │   ├── `push-gate-reconciliation-decision.md` - Push-gate reconciliation — decision to keep
│   │   ├── `qa-status-gate-gap-orchestrator-side-20261005.md` - The QA-verdict gate does not cover the orchestrator — still open 2026-10-05
│   │   ├── `quarantine-record-dev-20260915-020044.md` - Quarantine record: phantom `/dev` cycle `dev-20260915-020044`
│   │   ├── `recoverable-discard-register-20261005.md` - Recoverable-discard register — 2026-10-05 tree-to-zero campaign
│   │   ├── `rename-execution-plan.md` - Rename execution plan — `awesome-claude-harness` → `claude-code-guardrails`
│   │   ├── `restart-detector-quota-text-match-false-positive-20260915.md` - `/restart` interruption detector: textual quota-proxy instead of structural liveness check
│   │   ├── `roadmap-decomposition-productization.md` - Roadmap: Monolith Decomposition + Productization
│   │   ├── `slashcommand-quick-reference.md` - Slash Command Quick Reference
│   │   ├── `subagentstop-payload-s0-measurement-20260929.md` - SubagentStop payload availability — S0 measurement (2026-09-29)
│   │   ├── `test-suite-overhaul-plan.md` - Test Suite Overhaul Plan (Plan-of-Record)
│   │   ├── `tmp-cleanup-convention.md` - Ad-hoc scratch directory convention
│   │   ├── `tmpfs-persistent-backups-20261005.md` - Persistent-disk backups of the tmpfs-only checkout (2026-10-05)
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
│   │   ├── `hook_ledger.py` - hooks/doc_sync/main.py calls record_landed_files() right after
│   │   ├── `ledger_contract.py` - Before this module, the producer (hooks/doc_sync/hook_ledger.py) and the
│   │   ├── `main.py` - Main entry point for doc-sync hook.
│   │   ├── `notice.py` - A skipped README, INDEX or CLAUDE.md section is a deliberate outcome (regeneration is opt-in
│   │   ├── `patch.py` - Patch CLAUDE.md dynamic sections using AUTO markers.
│   │   ├── `regen_index.py` - Regenerate INDEX.md for a directory.
│   │   ├── `regen_readme.py` - Regenerate README.md for a directory.
│   │   ├── `regions.py` - Four unrelated predicates used to decide what a file's AUTO region is (README first
│   │   ├── `systemd.py` - Query systemctl for project-configured services and generate a markdown table.
│   │   └── `tree.py` - Build directory trees for INDEX.md.
│   ├── git-hooks/
│   │   ├── `post-commit-auto-push` - post-commit-auto-push file
│   │   └── `pre-commit` - pre-commit file
│   ├── git-keystone/
│   │   └── `reference-transaction` - reference-transaction file
│   ├── lib/
│   │   ├── runtime_guard/
│   │   ├── `agent_resolver.py` - Refactored from pretool-subagent-code-block.py::_find_agent_type so that
│   │   ├── `agent_temp_targets.py` - This module is deliberately not an authorization hook and never emits
│   │   ├── `allowlist.py` - Single source of truth for grant-read, grant-match, and grant-consume
│   │   ├── `attribution_journal.py` - Capture side (used by pretool-attribution-pre.py / posttool-attribution-post.py):
│   │   ├── `bash_context_strip.py` - This is deliberately NOT a full shell parser.  It only computes a conservative
│   │   ├── `bash_write_targets.py` - Provides two public functions used by tool-policy and overnight-hook-guard:
│   │   ├── `capability_state.py` - verdict, and the INDEPENDENT (non-hook-dispatched) preactivation consumer
│   │   ├── `checkpoint-core.sh` - checkpoint-core.sh - Shared library for automated snapshot commits
│   │   ├── `checkpoint_resources.py` - The directory lock is the transaction boundary: primary-template validation,
│   │   ├── `claude_home.py` - Generalizes the in-repo gold-standard fail-closed self-resolution pattern
│   │   ├── `claude_home.sh` - claude_home.sh — shared "harness home" resolver (shell consumable).
│   │   ├── `close-verdict.py` - Shared CLOSE verdict classifier for commit/close tooling.
│   │   ├── `closeout.py` - Public API:
│   │   ├── `commit_journal.py` - WHY THIS EXISTS
│   │   ├── `contract_runtime.py` - This module is the single shared engine consumed by every contract-aware
│   │   ├── `dev_report_shard_patterns.py` - Single source for the per-worker / canonical dev-report filename regexes and
│   │   ├── `git_clean_guard.py` - Classifies ONE Bash command for the fail-closed pre-clean guard woven into the
│   │   ├── `git_command_classifier.py` - Provides iter_git_invocations() — a token-aware parser that detects git
│   │   ├── `grepguard_context_strip.py` - PURPOSE (narrow, guard-specific)
│   │   ├── `harness_state_dir.py` - Hook runtime state (consent flags, grants, sentinels, bookmarks, stamps) lives
│   │   ├── `harness_state_dir.sh` - harness_state_dir.sh -- shell twin of hooks/lib/harness_state_dir.py.
│   │   ├── `interruption_signals.py` - Decides whether a subagent was cut off — and whether a usage limit did it — from
│   │   ├── `negative_evidence.py` - The scan root is never an authority source.  A parent-published immutable
│   │   ├── `obligation.py` - Rollout step S2 of the converged zero-failure design
│   │   ├── `overnight.py` - Single source of truth for "is a /dev-overnight session currently live?". A
│   │   ├── `policy_registry.py` - Reads the harness ``policies/tool-policy.v1.json`` (resolved via the shared
│   │   ├── `progress_measure.py` - escalate when it is not, and never release
│   │   ├── `runtime_guard.py` - This file exists for backwards-compatibility with callers that invoke
│   │   ├── `schema_registry.py` - Reads schemas/registry.json once and lazily loads referenced schema files
│   │   ├── `session_resources.py` - Every destructive operation is bound to an immutable resource session and a
│   │   ├── `specialist_yield.py` - Public API:
│   │   ├── `subagent.py` - Single source of truth for is_subagent_context() and supporting helpers
│   │   ├── `subagent_restart.py` - Claude Code persists each subagent transcript under the parent session.  This
│   │   └── `todo_canonical.py` - Shared canonical todo validation utilities
│   ├── tests/
│   │   ├── fixtures/
│   │   ├── `_fixtures_obligation_terminal.py` - 20260930-132644-l4): hooks/tests/test_stop_obligation_gate.py and
│   │   ├── `test_ac10_verify.sh` - Shell script
│   │   ├── `test_ac1_verify.sh` - Shell script
│   │   ├── `test_ac3_verify.sh` - Shell script
│   │   ├── `test_ac5_verify.sh` - Shell script
│   │   ├── `test_ac6_verify.sh` - Shell script
│   │   ├── `test_ac9_verify.sh` - Shell script
│   │   ├── `test_allowlist_consolidation.py` - Covers AC8 IS_SUBAGENT firewall scenarios and matching semantics invariants
│   │   ├── `test_allowlist_git_global_opts.py` - Regression cover for task 20260928-133915: `/allow git commit` could never match
│   │   ├── `test_artifact_contract_enforce.py` - The hook is the producer-side port of /close's Artifact schema gate
│   │   ├── `test_attribution_adjudicator.py` - canonical aggregate view (Phase C; purely additive artifacts, nothing switched)
│   │   ├── `test_attribution_journal.py` - break detection, verify script verdicts, torn-tail handling, seal
│   │   ├── `test_baseline_snapshot_preflight.py` - agents/dev.md:535 declares that the orchestrator captures baseline_dirty_snapshot
│   │   ├── `test_bash_safety_context.py` - Tests strip_non_executable_contexts() in isolation, covering the main
│   │   ├── `test_bash_safety_context_rules.py` - converted to COMMAND_CONTEXT_STRIPPED in hooks/pretool-bash-safety.sh
│   │   ├── `test_bash_safety_git_clean.py` - hooks/pretool-bash-safety.sh (task dev-20260719-150041-a, lane r01-a)
│   │   ├── `test_bash_write_targets_policy.py` - Execution-semantic write-target resolution at the exact sink use site.
│   │   ├── `test_blackbox_integration.py` - WHAT THIS PROVES, AND WHAT IT EXPLICITLY DOES NOT
│   │   ├── `test_block_branch_pr_worktree.py` - The hook forbids branch / PR / worktree CREATION on the Bash surface, with three
│   │   ├── `test_bulk_commit_sentinel.py` - Covers:
│   │   ├── `test_capability_gate.py` - Every test drives the real artefacts: the library, the PreToolUse gate hook as a
│   │   ├── `test_checkpoint_pii_gate.sh` - Regression tests for the checkpoint PII/credential hard-exclude + push gate
│   │   ├── `test_close_verdict_round_open.py` - `CLOSE_FINDINGS: <n> items` is the never-landing return of a QA judging round
│   │   ├── `test_commit_journal.py` - attribution basis
│   │   ├── `test_contract_runtime_version_dispatch.py` - hooks/lib/contract_runtime.py (ticket 20260929-104216-a, zero-failure design
│   │   ├── `test_cp_checkin.py` - of ba-spec-20260427-194324.md (P1 view-trigger removal + P2 generation field)
│   │   ├── `test_do_block_subagents.py` - During an active /do cycle the main agent could still dispatch dev-type
│   │   ├── `test_do_taskid_mint.py` - Covers the root-cause fix for the do-report task-id collision (memory
│   │   ├── `test_doc_sync_hook_ledger.py` - hook-authored side-effect files (backlog #122, M1/M2)
│   │   ├── `test_doc_sync_hook_notices.py` - Backlog #83: a README that regen_readme() skips (no opening marker, or no closing marker)
│   │   ├── `test_doc_sync_index_notices.py` - Backlog #85: the INDEX regeneration path and the CLAUDE.md section patcher now report what
│   │   ├── `test_doc_sync_index_status.py` - Backlog #85: regen_index() returned None on every path, so nobody could tell a skipped INDEX
│   │   ├── `test_doc_sync_regen_readme_status.py` - Backlog #83: regen_readme() returned None on every path, so nobody could tell a skipped
│   │   ├── `test_doc_sync_regions.py` - Backlog #85: four unrelated marker predicates (README first occurrence, INDEX substring
│   │   ├── `test_dual_runtime_lifecycle_e2e.py` - Real-entrypoint regressions for single-owner ordinary dev lifecycle.
│   │   ├── `test_e2e_enforce.py` - obligation fallback (ticket 20261001-161041-r06, M1)
│   │   ├── `test_extract.py` - Unit tests for hooks/doc_sync/extract.py — covers all 4 defects + known-file cases.
│   │   ├── `test_fail_closed_drift.py` - WHY THIS FILE EXISTS
│   │   ├── `test_final_sweep.sh` - Final sweep — run inline AC checks and print PASS/FAIL summary.
│   │   ├── `test_git_cmd_cross_consistency.py` - Verifies that GIT_CMD_RE (hooks/pretool-bash-safety.sh),
│   │   ├── `test_git_prefix_enumeration.py` - THE DEFECT
│   │   ├── `test_git_residual_override.py` - Background
│   │   ├── `test_gitignore_preflight_close_contract.py` - The gate previously harvested any docs/dev/dev-report-*.json cited anywhere in an
│   │   ├── `test_grep_backtrack_guard.py` - Freeze safe grep shapes and the catastrophic embedded-engine control.
│   │   ├── `test_laneb_agent_temp_targets.py` - Complete declared static temp-target mechanism matrix for LANE-B.
│   │   ├── `test_laneb_checkpoint_resources.py` - LANE-B checkpoint transaction and CLI provider tests.
│   │   ├── `test_laneb_integration_gate.py` - Adversarial tests for the closed Lane B H-B v3/fan-in verifier.
│   │   ├── `test_laneb_pretool_composition.py` - LANE-B core seams for the later POL/BIND single-writer integration.
│   │   ├── `test_laneb_session_resources.py` - LANE-B actor scratch, receipt, and owned-process broker tests.
│   │   ├── `test_laneb_stop_coordinator.py` - LANE-B non-destructive receipt writers and serialized Stop coordinator.
│   │   ├── `test_laneb_stop_overnight_timelock_scoping.py` - Blast-radius-map.json (dev-20260910-111227/blast-radius-map-20260808-035658-laneb)
│   │   ├── `test_obligation.py` - Covers the four implementation ACs of ticket-20260929-104216-b:
│   │   ├── `test_obligation_gate.py` - G1 is the first of five enforcement doors (spec-20260930-092323) that move
│   │   ├── `test_overnight_gitenv_failclosed.py` - Two halves of one fail-open, scoped together because closing either alone leaves
│   │   ├── `test_overnight_qa_sentinel_bind.py` - `_qa_mode_sentinel_rw_bind` / `_build_bwrap_argv` had ZERO test callers, so the
│   │   ├── `test_overnight_state_file_write_guard.py` - overnight-state write-protection (ticket 20261001-161041-r10, AC4/AC5/AC6)
│   │   ├── `test_overwrite_guard.py` - Every assertion drives the REAL guard as a subprocess over a synthetic
│   │   ├── `test_posttool_commit_grant_finalize.py` - hooks/posttool-allowlist-consume.py, and for the pointer WRITE side in
│   │   ├── `test_posttool_overnight_loop_terminal_gate.py` - (ticket 20260930-132644-l4)
│   │   ├── `test_posttool_push_gate_token_verify.py` - THE GAP THIS HOOK CLOSES. agents/changelog-analyst.md Phase 10 writes the push-gate
│   │   ├── `test_progress_measure.py` - Only throwaway directories are used; the helper is imported by file path so
│   │   ├── `test_push_gate_ancestor_cross_session.sh` - Regression test for hooks/push.sh's push-gate token scan (task 20260924-031253):
│   │   ├── `test_push_no_upstream_guard.sh` - Regression test for hooks/push.sh R22 (line ~375): HAS_UPSTREAM must be
│   │   ├── `test_push_sentinel_abort.sh` - Unit test for AC1 V5: hooks/push.sh self-aborts before any real git push
│   │   ├── `test_regen_index_dirs_script.py` - Backlog #85: the script printed `regenerated: <INDEX>` for every directory, including the ones
│   │   ├── `test_residual_false_positives.py` - Context (task 20260903-residual-fp). `classify_git_command()` returns a
│   │   ├── `test_runcode_watchdog_aliases.py` - Direct lifecycle parity tests for both browser run-code provider names.
│   │   ├── `test_runtime_guard.py` - Two layers:
│   │   ├── `test_scratch_lifecycle.py` - Covers:
│   │   ├── `test_sessionstart_artifact_census.py` - Every run is a subprocess against throwaway directories; the real restart
│   │   ├── `test_stop_do_report_gate.py` - Covers the contract from commands/do.md Step 5: a /do session may stop only
│   │   ├── `test_stop_obligation_gate.py` - gate, ticket 20260930-132644-l4)
│   │   ├── `test_tool_policy_contracts.py` - LANE-POL least-privilege role-policy regression matrix.
│   │   ├── `test_unit_anchor.py` - Imports the anchor sibling module DIRECTLY (not via the _core facade) and
│   │   ├── `test_unit_config.py` - Imports the config sibling module DIRECTLY (not via the _core facade) and
│   │   ├── `test_unit_constants.py` - Imports the constants sibling module DIRECTLY (not via the _core facade) and
│   │   ├── `test_unit_find_cmds.py` - Imports the find_cmds sibling module DIRECTLY (not via the _core facade) and
│   │   ├── `test_unit_git_cmds.py` - Imports the git_cmds sibling module DIRECTLY (not via the _core facade) and
│   │   ├── `test_unit_pathmatch.py` - Imports the pathmatch sibling module DIRECTLY (not via the _core facade) and
│   │   ├── `test_unit_shell_lex.py` - Imports the shell_lex sibling module DIRECTLY (not via the _core facade's
│   │   ├── `test_userprompt_doc_sync_relay.py` - Backlog #83: the UserPromptSubmit hook resyncs a directory by running
│   │   └── `test_userprompt_usage_snapshot.py` - Covers the three cache states the hook must handle (cache hit, cache expired
│   ├── `audit-slashcommand.sh` - audit-slashcommand.sh
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
│   ├── `notification-idle-overnight.py` - Notification hook: Observe overnight idle events
│   ├── `post-commit-warn.sh` - post-commit-warn.sh - Warn about untracked files after commit
│   ├── `post_tool_use.sh` - PostToolUse Hook - Code quality hints after file modifications
│   ├── `posttool-allowlist-consume.py` - PostToolUse Hook: /allow grant consumption
│   ├── `posttool-attribution-post.py` - Pairs with pretool-attribution-pre.py via (session_id, tool_use_id). Purely
│   ├── `posttool-codex-skill-ledger.py` - Fires on every PostToolUse for the Skill tool. When tool_input.skill == "codex",
│   ├── `posttool-command-frontmatter-validate.py` - PostToolUse Hook: Validate .claude/commands/*.md frontmatter structure
│   ├── `posttool-doc-sync.py` - PostToolUse Hook: Auto-sync INDEX.md and CLAUDE.md when structural files change
│   ├── `posttool-git-checkpoint.sh` - posttool-git-checkpoint.sh - PostToolUse checkpoint trigger
│   ├── `posttool-git-warn.sh` - post-commit-warn.sh - Warn about untracked files after commit
│   ├── `posttool-lane-completeness-watch.py` - instant a lane-shard dev-report write completes its declared lane_set
│   ├── `posttool-overnight-file-check.py` - PostToolUse:Agent Hook — Contract-driven overnight file check
│   ├── `posttool-overnight-loop.py` - PostToolUse:TodoWrite Hook: Overnight Loop Detection
│   ├── `posttool-overnight-trace.py` - Writes one JSONL trace record per Agent invocation to:
│   ├── `posttool-push-gate-token-verify.py` - PostToolUse Hook: write-time validation of the push-gate token's commit_sha
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
│   ├── `pretool-cp-checkin.py` - cp-state file read
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
│   ├── `pretool-push-analyst-grant-guard.py` - PreToolUse Hook: independent re-validation of the push-analyst Chain-B grant
│   ├── `pretool-quality-gate.py` - PreToolUse Hook: Quality gate for Write/Edit operations
│   ├── `pretool-read-size-guard.py` - PreToolUse Hook: Read Size Guard
│   ├── `pretool-runcode-watchdog.py` - PreToolUse Hook: Start timeout watchdog for browser_run_code
│   ├── `pretool-spec-block-foreground-agent.py` - PreToolUse Hook: Block foreground Agent during an active /spec Interview
│   ├── `pretool-subagent-code-block.py` - Canonical enforcement: pretool-tool-policy.py + lib/policy_registry — this
│   ├── `pretool-subagent-enforce.py` - PreToolUse:Agent Hook — Contract-driven role/pipeline enforcement
│   ├── `pretool-todo-validate.py` - PreToolUse Hook: Validate TodoWrite input BEFORE execution
│   ├── `pretool-tool-policy.py` - Single hook that consumes the harness ``policies/tool-policy.v1.json`` (resolved
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
│   ├── `sessionstart-artifact-census.py` - Enumerates and notifies only. Every unclosed chain gets a queue record; the
│   ├── `start-fswatch-all.sh` - start-fswatch-all.sh - Start fswatch monitoring for all important repositories
│   ├── `stop-cleanup-allowlist.sh` - Stop Hook: Wipe any unconsumed /allow grant at turn end.
│   ├── `stop-completion-gate.py` - completion obligation is open (ticket 20261001-161041-r08; reworked by
│   ├── `stop-do-report-gate.py` - A /do session mints a task-id sidecar (/tmp/claude-do-task-<sid>.json) and a
│   ├── `stop-obligation-gate.py` - A dev-family session (/dev, /dev-command, /redev, or any /dev-overnight-
│   ├── `stop-overnight-timelock.py` - Stop Hook: Block conversation termination until overnight end-time
│   ├── `stop-spec-coverage-enforce.py` - Stop Hook: Block spec agent from exiting with < 100% monolith coverage
│   ├── `stop-workflow-coordinator.py` - LANE-B (20260808-035658) M4/M7: registered as the harness's actual Stop hook,
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
│   ├── `changelog-status.v1.json` - Validates the JSON payload of the '--- CHANGELOG-ANALYST-STATUS-BEGIN ---' / '--- CHANGELOG-ANALYST-STATUS-END ---' response block (agents/changelog-analyst.md '### Output schema' / '### Structured output sentinel'). This schema is a DESCRIPTION of an already-existing, already-correct output format (lane L7 of spec-20260930-092323) -- it formalizes the prose for obligation-block validation (schemas/obligation.v1.json's response_block artifact kind) and does not change what changelog-analyst emits. additionalProperties false at every level: a drifted/unexpected field is a shape bug worth surfacing, not silently accepted.
│   ├── `cleanliness-inspector-report.v1.json` - Report written by the cleanliness-inspector subagent (agents/cleanliness-inspector.md), dispatched by /close Step 1. Required set is the intersection of (a) the agent's own canonical Output Format block (agents/cleanliness-inspector.md:293-327: request_id/timestamp/inspector/findings/summary) and (b) its codex_consult mandate -- verified >=97% present across a live sweep of all on-disk docs/dev/cleanliness-inspector-report-*.json samples this session (ticket 20261001-161041-r11; 'findings' is a dict in 192/198 present cases, matching the agent's documented category-keyed shape). 'mode' was DELIBERATELY EXCLUDED from required (and from `properties`) after that same sweep showed it is NOT part of the agent's documented contract: it is missing from 8/204 reports, and -- more importantly -- is a string in 190 cases but a nested OBJECT in 6 real, current (2026-09/10) reports, so a `type` constraint on it would spuriously fail legitimate variants either way. additionalProperties: true lets 'mode' and every other cycle-specific field pass through unvalidated.
│   ├── `context.v1.json` - BA-produced wave/task plan and root cause analysis. Read by dev subagents to understand implementation scope.
│   ├── `cycle-contract.v1.json` - Single source of truth per overnight cycle. Mirrors architect.contract_manifest_schema.json_shape from architect-spec-20260426-090235.json. Written by the orchestrator at end of Step 2c (PM Triage) and again at end of Step 3 (after pipeline IDs are known). Read by the contract-aware hooks (pretool-subagent-enforce, posttool-subagent-track, posttool-overnight-file-check) and check-overnight-reports.py.
│   ├── `dev-report.v1.json` - Per-task dev implementation report. Read by QA, PM RETRO, and the closeout aggregator.
│   ├── `dev-report.v2.json` - Per-task dev implementation report, v2: matches the REAL nested producer template (agents/dev.md:590-674 — nested dev.status, top-level baseline keys) instead of v1's flat shape. Required baseline_head_sha/baseline_dirty_snapshot mirror the live producer checks at scripts/aggregate-dev-report.py:529-546 (commit inventory #71/#72, close #20/#22; empty string is legal for both — unborn repo / clean tree). The AC-deviation sub-shape is copied from its canonical machine-shape definition at scripts/resolve-dev-artifact-chain.py:80-130. lane/lane_set follow docs/reference/close-commit-zero-failure-mechanism-20260928.md §1.1(e)/§1.2: lane_set is required non-null when lane is a string; lane-membership (lane ∈ lane_set) is NOT expressible in Draft7 and is the later G2 echo check, deliberately not faked here. Authority: design §1.6 (schema v2 cutover).
│   ├── `do-report.v1.json` - Lightweight /do completion report. Skeleton is hook-authored at consent time (status=pending); the agent MUST rewrite it to a terminal status before session stop (enforced by hooks/stop-do-report-gate.py). Read by /close (do-report path) and /commit.
│   ├── `graphify-focused-subgraph.v1.json` - Task-scoped subgraph extracted from the global Graphify knowledge graph, focused on files in the BA blast-radius-map. Written to .claude/dev-registry/{task_id}/graphify/focused-subgraph.json by graphify-enrich.py.
│   ├── `graphify-prequery.v1.json` - Step 1.5 output from graphify-query.py. Contains structural_context extracted from the global Graphify cache before BA analysis. Status field drives BA behaviour: ok/degraded proceed, unavailable/skipped silently bypass.
│   ├── `graphify-run.v1.json` - Step 7.5 run manifest. Records the graphify subagent's execution: update run, focused subgraph extraction, and context patching status.
│   ├── `negative-evidence.v1.json` - Authority-bound bounded negative evidence receipt
│   ├── `obligation.v1.json` - Validates the JSON payload of the <obligation v="1"> block per docs/reference/close-commit-zero-failure-mechanism-20260928.md §1.2 (the XML wrapper itself is the S2 grammar library's concern, not this schema's). additionalProperties false at the top level: G1's job is shape-rejection of drifted blocks (design M5/M7/M28); cross-version tolerance is carried by the wrapper's v attribute (M29), not by an open v1 object. Path fields (artifacts[].path, expected_absent[]) are repo-relative and traversal-free (must not start with '/', must not contain '..'); G1 re-checks at dispatch — the schema encodes the invariant so a registered grammar exists (G1 check 2). The null-task_id gate's expressible half is encoded (profile outside {ad_hoc, commit-bulk, commit-qa} forces a string task_id); commit-qa's context-dependence (bulk-context null vs task-scoped string) is enforced by G1 later, not by this schema. lane-membership (lane ∈ lane_set) is the later G2 echo check, not expressible in Draft7.
│   ├── `owned-edits-ledger.v1.json` - Machine-readable definition of the owned-edits ledger a dev-report must carry so that scripts/stage-owned-hunks.py can stage this cycle's owned hunks. DERIVED FROM THE CONSUMER'S CODE, not from agent prose; see x-consumer for the digest it is derived from and x-citation-policy for why nothing here cites a line number. Plus the snapshot-materialization rule in agents/changelog-analyst.md, locatable by searching for '2. Snapshot materialization (REQUIRED', which is the only place the report-level pre_edit_snapshots map is turned into the --snapshot file the consumer reads. Where prose and code disagree, the code governs; see x-prose-code-disagreements below.
│   ├── `paseo-dossier.v1.json` - Structured sidecar validated by scripts/paseo-daemon-ledger.py dossier-validate. Fail-closed: a dossier missing any required F12 field, or carrying a malformed seven-field decision-journal record, must never become a committed generation. The dossier is an index and checkpoint ONLY — authoritative evidence remains the session transcript and hash-verified artifact files.
│   ├── `prompt-inspector-report.v1.json` - Report written by the prompt-inspector subagent (agents/prompt-inspector.md), dispatched by /close Step 1. Required set is the intersection of (a) the agent's own canonical Output Format block (agents/prompt-inspector.md:150-179: request_id/timestamp/inspector/findings/summary) and (b) its codex_consult mandate -- verified >=97% present across a live sweep of all on-disk docs/dev/prompt-inspector-report-*.json samples this session (ticket 20261001-161041-r11; 'findings' is a list in 190/190 present cases, matching the agent's documented array shape). 'mode' was DELIBERATELY EXCLUDED from required (and from `properties`) after that same sweep showed it is NOT part of the agent's documented contract: it is missing from 17/194 reports, and is a string in 172 cases but a nested OBJECT in 5 real, current (2026-09) reports, so a `type` constraint on it would spuriously fail legitimate variants either way. additionalProperties: true lets 'mode' and every other cycle-specific field pass through unvalidated.
│   ├── `qa-report.v1.json` - QA verdict + evidence summary for a single pipeline. When ui_pipeline=true, evidence_summary.ui_evidence MUST satisfy the ui-specialist's ui_evidence_schema fragment (target_route, target_element, viewports {desktop, mobile}, evidence_map keyed AC-N, trace, captured_at). Custom keyword 'required_when_ui' is enforced by lib/contract_runtime.validate() as a pre-validation pass before the standard jsonschema Draft7Validator runs.
│   ├── `qa-report.v2.json` - QA verdict report, v2: matches the REAL nested producer (agents/qa.md:1393 — nested qa.status mandated; top-level status MUST NOT be emitted because commit.sh:547-556 reads only data['qa']['status']). Top-level verdict is likewise forbidden: no producer emits it and schemas/qa-report.v1.json:8-14 REQUIRES it, so forbidding it here shape-rejects flat v1-relic records misdeclared as report_version 2. qa.e2e_enforcement.status carries the FULL recognized vocabulary of hooks/subagentstop-e2e-enforce.py:41 (PASSING_STATUSES) plus its explicitly-recognized blocking value skipped_without_justification (:270): the schema validates SHAPE, the e2e stop gate keeps enforcing POLICY — narrowing the enum would make an honestly-reported skip a schema-forgery incentive. NO baseline_head_sha/baseline_dirty_snapshot here: the qa producer template (agents/qa.md:1398-1621) does not emit them (QA reads them from the dev report, agents/qa.md:468). lane/lane_set follow design §1.1(e)/§1.2 (lane-membership is the later G2 echo check, not schema-checked). Authority: docs/reference/close-commit-zero-failure-mechanism-20260928.md §1.6.
│   ├── `registry.json` - JSON config: schemas
│   ├── `repair-map.v1.json` - JSON config: _kind, $comment, generated_by, entry_count, entries
│   ├── `style-inspector-report.v1.json` - Report written by the style-inspector subagent (agents/style-inspector.md), dispatched by /close Step 1. Required set is the intersection of (a) the agent's own canonical Output Format block (agents/style-inspector.md:598-621: request_id/timestamp/inspector/violations/summary) and (b) its separately-mandated 'codex_consult field MUST be present in all outputs' rule (agents/style-inspector.md:732) -- verified >=96% present across a live sweep of all on-disk docs/dev/style-inspector-report-*.json samples this session (ticket 20261001-161041-r11). 'mode' and 'standards_passed' were DELIBERATELY EXCLUDED from required after that same sweep showed they are NOT part of the agent's documented contract and are absent from 16-35% of real reports (mode: 71/201 missing; standards_passed: 33/201 missing) -- requiring either would spuriously fail a large fraction of legitimate reports, violating the ticket's 'required kept conservative' constraint. additionalProperties: true lets both (and every other cycle-specific field) pass through unvalidated.
│   ├── `test-plan.v1.json` - Unified PM-produced test plan. This schema replaces both legacy 'test-plan.json' and 'test-plan-*.json' shapes (per spec-20260426-090235 Section 7 P2 #3 — single canonical naming). additionalProperties:true preserves the existing rich PM payload (priority_tiers, recommended_specialists, pm_experience, app_context, agent_assignments, core_flow_gate, ...).
│   ├── `test-writer-manifest.v1.json` - Per-task active test manifest (tests/generated/<task_id>/manifest.json). Field shapes pinned verbatim to agents/test-writer.md:90-112 (ticket 20261001-161041-r07). This is the PER-TASK active manifest, distinct from the global index file tests/generated/manifest.json (shape {kind:'index', tasks:[...]}), which this schema does NOT cover. Registered so the test-writer obligation block can name this artifact and the generic SubagentStop obligation-mode loop in hooks/subagentstop-artifact-contract-enforce.py enforces its presence/shape -- no enforcement code changed by this registration.
│   └── `test-writer-report.v1.json` - Per-task test-writer report (docs/dev/test-writer-report-<task_id>.json). Field shapes pinned verbatim to agents/test-writer.md:206-223 (ticket 20261001-161041-r07). Registered so hooks/lib/contract_runtime.validate_artifact_for_obligation can resolve a real schema instead of permanently returning 'skip' for an unregistered id. Consumed read-only by the generic SubagentStop obligation-mode loop in hooks/subagentstop-artifact-contract-enforce.py -- no enforcement code changed by this registration.
├── scripts/
│   ├── install/
│   │   ├── profiles/
│   │   ├── tests/
│   │   ├── `install` - install file
│   │   ├── `installer.py` - Subcommands: plan | apply | uninstall | snapshot
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
│   │   ├── `dispatch_metadata.py` - answer "which bytes are this task's" -- (1) nothing records which agent identity
│   │   ├── `make_sbom.py` - The SBOM is built from the archive's real contents, not from the source
│   │   ├── `release_membership.py` - Single source of truth shared by every consumer, so the archive builder, the
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
│   ├── `capture-dispatch-metadata.py` - dispatch-time baseline content for files already dirty at dispatch) in the --lanes
│   ├── `capture-hero-run.py` - Description: Builds a hermetic fixture, installs one narrowly-scoped single-use grant,
│   ├── `check-enforcement-evidence.py` - Three subcommands, one consumer each:
│   ├── `check-file-references.sh` - File reference detection script - used by /clean command
│   ├── `check-late-repair-provenance.py` - Takes ONLY ``--task-id`` and ``--project-dir`` (never a caller-supplied file
│   ├── `check-overnight-reports.py` - Description: Validates all overnight required outputs declared by the active
│   ├── `check-overnight-reports.sh` - DEPRECATED — replaced by check-overnight-reports.py per spec-20260426-090235 P0/M5.
│   ├── `check-public-core.sh` - Description: Public/private boundary gate. Recomputes the top-level tracked-path set from
│   ├── `check-readme-freshness.sh` - Check README.md freshness for all major folders
│   ├── `check-security-hook-drift.sh` - Description: Audit always-on security-critical hook files against a cycle baseline SHA
│   ├── `check-todo-accounting.py` - Executable C10 accounting proof for the ordinary ``/dev`` checklist.
│   ├── `checkpoint-prune.sh` - checkpoint-prune.sh — trim refs/checkpoints/* to the most recent N commits
│   ├── `cleanup-close-force-sentinel.sh` - Removes the force-close sentinel file for a given dev session.
│   ├── `close-commit-repair-orchestrate.py` - Consumes schemas/repair-map.v1.json; given a findings list, looks up each
│   ├── `close-report-append.py` - Description: Deterministic read-append-reread-verify helper for the
│   ├── `close-route-select.py` - Without ``--late-repair`` this is a pass-through: it resolves the artifact
│   ├── `close-scoring-decide.py` - Description: Decide which close_success_* event /close should issue based on
│   ├── `commit.sh` - Description: Discoverable canonical entrypoint for commands/dev-overnight.md's
│   ├── `create-overnight-state.sh` - create-overnight-state.sh — Create overnight state file (v7 schema)
│   ├── `create-worktree.sh` - Create a git worktree from local HEAD (not origin/main).
│   ├── `derive-default-branch.sh` - Description: Resolve the repository's default branch name dynamically (handles main/master/any other).
│   ├── `detect-dead-functions.sh` - Shell script
│   ├── `detect-duplicate-content.sh` - Shell script
│   ├── `detect-hardcoded-paths.sh` - Shell script
│   ├── `detect-merge-conflicts.sh` - Shell script
│   ├── `detect-orphan-agents.sh` - Description: Detect agents not referenced by any command
│   ├── `detect-orphan-commands.sh` - Description: Detect orphan commands (one-time patterns, no todo script, unused)
│   ├── `detect-orphan-scripts.sh` - Description: Detect scripts not referenced by any command/agent/other script
│   ├── `dev-fix.py` - This module is intentionally a backend, not a command orchestrator.  It classifies
│   ├── `dev-lifecycle.py` - Derives, per on-disk task-id, a state using the TOTAL REDUCTION ORDER from
│   ├── `discover-folders.sh` - Description: Dynamically discover project folders excluding system directories
│   ├── `doctor` - doctor file
│   ├── `execute-push.py` - Eliminates the timing window that exists when validate + push are && -chained
│   ├── `gen-test-baseline.py` - Usage:
│   ├── `generate-folder-index.sh` - Description: Generate INDEX.md for folder (inventory of contents)
│   ├── `generate-folder-readme.sh` - Description: Generate README.md for folder (purpose and organization rules)
│   ├── `generate-hero-status.py` - Description: One source of truth emits THREE marker-delimited canonical regions -- the
│   ├── `generate-repair-map.py` - Part A of ticket-20260930-132644-l8 (spec-20260930-092323 lane L8). Joins:
│   ├── `graphify-enrich.py` - graphify-enrich.py — pre-DEV focused subgraph extractor (runs between Step 7 and Step 8)
│   ├── `graphify-maintain.py` - graphify-maintain.py — Global Graphify cache lifecycle manager (REAL CLI)
│   ├── `graphify-query.py` - graphify-query.py — deterministic pre-BA graph hydrator (runs between Step 1 and Step 2)
│   ├── `graphify_lib.py` - graphify_lib.py — shared library for Graphify knowledge-graph integration
│   ├── `install-checkpoint-refspec.sh` - install-checkpoint-refspec.sh — idempotently add refs/checkpoints/* to
│   ├── `install-git-keystone.sh` - install-git-keystone.sh — wire the git-native reference-transaction keystone
│   ├── `iterate-failed-pipelines.py` - Reads pipelines JSON path; outputs iteration plan JSON to stdout. The orchestrator
│   ├── `laneb-integration-gate.py` - The program is deliberately non-authorizing unless it has consumed the complete,
│   ├── `late-repair-controller.py` - Owns the run-record lifecycle for the deliberately-invoked ``/close
│   ├── `lifecycle-baseline-import.sh` - Description: One-time idempotent migration — import current agent scores from agent-scores.json
│   ├── `lint-spec-id-centralization.py` - markdown from re-deriving a spec-id / views_dir / split_marker / cp_dir from a
│   ├── `measure-hero-fold.py` - Description: Renders README.md LOCALLY from the working tree in headless Chromium at the
│   ├── `migrate-test-to-tests.sh` - Description: Merge test/ folder into tests/ preserving all content (idempotent)
│   ├── `mint-git-blessed-token.sh` - mint-git-blessed-token.sh — issuer of the keystone blessed token (M12).
│   ├── `negative-evidence.py` - Create or verify authority-bound bounded negative-evidence receipts.
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
│   ├── `refine-context.sh` - refine-context.sh — merge QA-refined context with original context
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
│   ├── `spec-check.py` - Subcommands: check-in, mark, waive, status, check-out, unlock
│   ├── `spec-update-contract.py` - The command policy owns all writes.  This module deliberately has no mutation
│   ├── `stage-owned-hunks.py` - Stages ONLY this cycle's owned hunks within a single already-authorized file,
│   ├── `step7-spec-update.py` - Step 8 (Spec-update dispatch) reference harness — task 20260524-205206 iter-2
│   ├── `test` - test file
│   ├── `update-gitignore.sh` - update-gitignore.sh - Auto-update .gitignore with project-specific rules
│   ├── `update-overnight-state.sh` - update-overnight-state.sh — Atomically update overnight state file
│   ├── `verify-attribution-chain.py` - Folds each file's events across ALL session journals into a hash chain and
│   ├── `verify-claims-extended.sh` - Description: Extended headline-claims gate. Closes the four documented coverage gaps in
│   ├── `verify-claims.sh` - Description: Self-verifying headline-claims gate. Recomputes the wired-hook entry count and
│   ├── `verify-hero-provenance.py` - Description: Re-runs the demo, normalizes both outputs and byte-diffs them; verifies raw
│   ├── `verify-release-manifest.sh` - Description: Verify a PUBLISHED release artifact end-to-end, WITHOUT rebuilding it.
│   ├── `write-bulk-commit-sentinel.py` - Invoked from commands/commit.md Step 5 (BULK=true) to authorize the
│   ├── `write-codex-enforce.sh` - Writes codex-enforce.json into the dev-registry for the given session.
│   ├── `write-commit-grant.py` - Invoked from `commands/commit.md` Step 5 (non-bulk mode) to author a
│   ├── `write-e2e-enforce.sh` - Writes e2e-enforce.json into the dev-registry for the given session.
│   ├── `write-enforce-flag.sh` - Write one or more enforcement-flag sentinels into a dev-registry session dir.
│   ├── `write-git-residual-override.py` - Answers the "could not be statically classified" refusal emitted by
│   └── `write-qa-mode.sh` - Write or update qa_mode field in the QA sentinel file for a dev-registry session.
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
│   ├── baselines/
│   │   └── `default-run-failures.json` - JSON config: environmental_unbaselined, failing_node_ids, generator, invocation, schema_version
│   ├── fixtures/
│   │   ├── late_repair_golden/
│   │   ├── `canary-tool-policy.v1.json` - JSON config: _fixture, _purpose, _contract, policy_version, default_action
│   │   ├── `dev-todo-canonical-before.v1.json` - JSON config: $schema, canonical_compact_sort_keys_sha256, item_count, schema_version, source_bytes
│   │   ├── `paseo-usage-envelope-20260828.json` - JSON config: _comment, type, message
│   │   └── `paseo_cron_vendor_vectors.json` - JSON config: _what, provenance, positive, negative, horizon
│   ├── generated/
│   │   ├── 20260704-134650/
│   │   ├── 20260704-225139/
│   │   └── `manifest.json` - JSON config: schema_version, kind, tasks
│   ├── instructions/
│   │   ├── `execution-guide.md` - AI Test Execution Guide
│   │   └── `validation-guide.md` - AI-Driven Validation Guide
│   ├── reports/
│   │   └── `edge-case-analysis.json` - JSON config: analysis_timestamp, repository, total_commits_analyzed, edge_cases_found, analysis_period
│   ├── score-inject-contract/
│   │   ├── `runtime-verify.sh` - Description: Runtime verifier for the 4-field score-injection echo contract.
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
│   │   ├── `validate-posttool-ac-dev-20260524-205811.py` - QA verification for dev-20260524-205811: posttool-allowlist-consume.py AC tests
│   │   ├── `validate-step-numbering.py` - Validator: validate-step-numbering
│   │   ├── `validate-todowrite-requirement.py` - Validator: validate-todowrite-requirement
│   │   ├── `validate-venv-usage.py` - Validator: validate-venv-usage
│   │   └── `validate-workflow-json-cleanup.py` - Validator: validate-workflow-json-cleanup
│   ├── `_dev_lifecycle_fixtures.py` - NOT a test file itself (no test_ prefix, not collected by pytest). Imported by
│   ├── `_late_repair_fixtures.py` - Not collected by pytest (leading underscore).  Builds four representative
│   ├── `fresh-clone-bootstrap-smoke.sh` - Description: Fresh-clone bootstrap smoke — proves "core is runnable + guards engaged"
│   ├── `integration-test.sh` - integration-test.sh - Integration tests for git tracking solution
│   ├── `test-lock-detection.sh` - Test script to verify git lock file detection and handling
│   ├── `test_ac_deviation_fanout_consumer.py` - records and the lifecycle presentation of ``pass_with_exceptions``
│   ├── `test_ac_deviation_record_chain.py` - A dev report that legitimately records an acceptance-criteria deviation is
│   ├── `test_aggregate_dev_report.py` - Unit tests for scripts/aggregate-dev-report.py
│   ├── `test_aggregate_dev_report_hook_ledger.py` - ledger (backlog #122 M3): scripts/aggregate-dev-report.py's len(shards_info)
│   ├── `test_aggregate_dev_report_superseded_rounds.py` - aggregate dev-report silently dropped a retried lane's superseded round(s)'
│   ├── `test_bash_write_targets_verb_narrowing.py` - The library used to read a word that merely begins `cp-`/`mv-` (a checkpoint id such as `cp-01`, a
│   ├── `test_candidate_tree.py` - Every test builds its own throwaway git repository. None of them reads this
│   ├── `test_changelog_analyst_declaration_categories.py` - `agents/changelog-analyst.md` decides what a cycle commits by reading declaration
│   ├── `test_changelog_analyst_files_landed_whole_toctou.py` - `files_landed_whole` TOCTOU-safe stage-then-verify sequence (currently at
│   ├── `test_changelog_analyst_required_to_ship_sourcing.py` - unobtainable declaration must not be silently read as an empty one
│   ├── `test_checkpoint_provenance.py` - These modes are DORMANT: no command, agent definition, or hook invokes them by
│   ├── `test_close_report_append.py` - failure semantics (round-7 CRITICAL fix, ticket dev-20260919-135733)
│   ├── `test_codex_workflow_gate.py` - Regression tests for Codex-native workflow-plan compatibility.
│   ├── `test_commit_multi_repo_plan.py` - Python script
│   ├── `test_commit_sh_reachability.py` - commands/dev-overnight.md:1561 previously called a bare, unqualified
│   ├── `test_completeness_channel_invariant.py` - One defect with a producer half and a consumer half:
│   ├── `test_completeness_span_accounting.py` - halves on one code path
│   ├── `test_dev_artifact_chain_consumer_contracts.py` - Contract tests for shared /dev artifact-chain consumers.
│   ├── `test_dev_fix.py` - Contract, safety, CAS, consent, crash and recovery tests for Lane F.
│   ├── `test_dev_todo_accounting.py` - Python script
│   ├── `test_dev_todo_codex_native_parse.py` - The harness never imports or executes the canonical checklist; it ``ast.parse``s
│   ├── `test_empty_old_string_diagnosis.py` - A real cycle emitted twenty-one ledger entries whose `old` was the empty string
│   ├── `test_generate_repair_map.py` - Covers AC-L8-01..04 and AC-L8-13 (docs/dev/acceptance-criteria-20260930-132644-l8.json)
│   ├── `test_git_clean_guard_vectors.py` - The pre-clean WIP snapshot guard (task dev-20260719-150041-c, lane r03-c) is
│   ├── `test_graphify_scripts.py` - tests/test_graphify_scripts.py — smoke tests for scripts/graphify_lib.py
│   ├── `test_graphify_workflow_contract.py` - tests/test_graphify_workflow_contract.py — contract tests for graphify agent registration
│   ├── `test_hero_advance_cross_check.py` - tools/demo/audit.mjs measures a line's rendered right edge on a fixed monospace grid, using
│   ├── `test_interruption_signals.py` - Every banner asserted here was measured in the real transcript corpus under
│   ├── `test_late_repair_driftfree_effective_state.py` - scripts/late-repair-controller.py's ``resolve_effective_report_state`` is the
│   ├── `test_late_repair_route.py` - Covers AC-7..AC-11, AC-13, AC-14 (spec-20260907-115508-lawful-commit-channel.md,
│   ├── `test_mat_doc10_writer_order_contract.py` - Published by task 20260819-124121-r03 (LANE-SU, spec 20260808-035658)
│   ├── `test_negative_evidence.py` - Python script
│   ├── `test_no_artificial_lifecycle_ceremony.py` - Prevent host metadata ceremonies from becoming ordinary lifecycle gates.
│   ├── `test_overnight_guard_in_place_git.py` - Defect (2026-08-09): `hooks/pretool-overnight-hook-guard.py` blocked EVERY git
│   ├── `test_overnight_loop_tz.py` - Verifies the overnight loop hook compares end_time correctly against the
│   ├── `test_parent_cycle_claimant_reader.py` - THE DEFECT.  Admission to a cycle's ownership-completeness claimant set was
│   ├── `test_paseo_daemon_ledger.py` - MANDATORY pytest facade for lane 20260828-112025-b: collects EVERY test
│   ├── `test_paseo_daemon_timers.py` - scripts/paseo-daemon-timers.py (task 20260926-111239)
│   ├── `test_paseo_usage_read.py` - MANDATORY pytest facade for lane 20260828-112025-b: collects EVERY test
│   ├── `test_prompt_workflow_injection_cadence.py` - The defect: ``build_overnight_continuation`` emitted ONE payload at ONE cadence
│   ├── `test_prompt_workflow_liveness_tz.py` - Two defects, both reproduced before this suite was written:
│   ├── `test_public_core_residue_gate.py` - These are the discriminating controls for the "Make CI FAIL (not advisory) on
│   ├── `test_refusal_record_consumers.py` - This is the module named BY NAME as `check.cli_run.harness` by AC12 and AC14 of
│   ├── `test_release_pipeline_contract.py` - verifier
│   ├── `test_repair_map_call_site_coverage.py` - (ticket-20261001-161041-r19)
│   ├── `test_repair_orchestrate.py` - Covers AC-L8-05..08 and AC-L8-14..16
│   ├── `test_resolve_dev_artifact_chain.py` - Focused tests for the read-only /dev artifact-chain resolver.
│   ├── `test_resolve_spec_artifacts.py` - resolver) + the static centralization lint (AC-B4 cases 1-12, task 20260530-092123)
│   ├── `test_restart_command.py` - End-to-end unit coverage for the human-only /restart recovery protocol.
│   ├── `test_spec_check_agent_id_guard.py` - Lane b of task 20260921-134709. Self-contained and subprocess based: one scratch
│   ├── `test_spec_check_closed_slot.py` - task 20260921-134709)
│   ├── `test_spec_check_concurrent_marking.py` - hooks/pretool-cp-checkin.py (harness backlog #97)
│   ├── `test_spec_update_command_contracts.py` - Executable contracts for the three-purpose ``/spec-update`` policy.
│   ├── `test_specialist_yield.py` - Tests use a tmp dir for the yield log and the bundled production policy file
│   ├── `test_stage_owned_hunks_boundary.py` - content-anchor-retry boundary/coordinate-space defect (task 20260912-015952)
│   ├── `test_subagentstop_e2e_enforce.py` - Backlog: dev-20260923-083731 -- widen _find_latest_qa_report's correlation
│   ├── `test_todo_md_sync.py` - Regression tests for the session-start todo/Markdown drift detector.
│   ├── `test_tool_policy_inference_note.py` - inference note appended by hooks/pretool-tool-policy.py to a Bash write-target
│   ├── `test_write_qa_mode.py` - Root selection and zero-write failure tests for write-qa-mode.sh.
│   ├── `TESTING.md` - Test Topology & Runner Map (authoritative)
│   ├── `verify-stop-spec-session-isolation.sh` - QA verification harness for stop-spec-coverage-enforce.py session isolation fix.
│   └── `ws2_zero_literal_gate.py` - Scans the EXPLICITLY-defined load-bearing surfaces of a rendered fresh clone with
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
├── `NESTED-REPO.md` - Nested Repo Sentinel
├── `NOTICE` - NOTICE file
├── `PUBLIC-CORE.md` - PUBLIC-CORE.md — public/private boundary manifest
├── `push.sh` - push.sh - Global pre-push checks: git identity + fetch/pull/status
├── `pytest.ini` - ini file
├── `release-membership.v1.json` - EXPLICIT release-membership manifest: the exact set of tracked paths that ship in a release archive. Membership is an edit to this file, never a silent consequence of a class rule. It is deliberately NOT 'public-core + all shared/infra': PUBLIC-CORE.md calls tests/ 'not itself the shippable harness', so a blanket class rule would drag non-shippable fixtures into the distribution. It is also not public-core-only: requirements.txt and requirements/ are shared/infra yet are required to install, so a public-core-only archive would be unusable.
├── `requirements.txt` - Python dependency manifest for the Claude Code harness venv
├── `settings.json` - Claude Code harness configuration (permissions, hooks, env, model)
├── `settings.template.json` - Distributable harness settings template (uses CLAUDE_HOME placeholders)
└── `VERSION` - VERSION file
```
<!-- /AUTO:index-stats -->

# .claude

---
*Auto-generated by doc-sync hook.*