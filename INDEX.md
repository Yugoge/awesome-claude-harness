# dot-claude

<!-- AUTO:index-stats -->
*Last updated: 2026-06-15T10:19:47Z*
**Total entries**: 448
**Convention**: kebab

## Tree
```
dot-claude/
├── agents/
│   ├── `architect.md` - Architecture review specialist for overnight exploration. Identifies structural issues, technical debt, optimization opportunities, dependency problems, and pattern inconsistencies. Returns structured JSON report.
│   ├── `ba.md` - Business analyst subagent for requirements analysis and context building. Receives user requirement text, performs git analysis, identifies affected files, and returns either clarification questions or dual-format output (Markdown spec + JSON context).
│   ├── `changelog-analyst.md` - Agentic commit subagent. Reads git state and dev-report to classify files, stages them, writes conventional commit messages (diff-first), handles nested repo, and writes push-gate token. Dispatched exclusively by /commit.
│   ├── `cleaner.md` - Cleanup execution specialist. Executes approved cleanup actions from cleanliness-inspector and style-inspector reports. Returns structured JSON execution report with results.
│   ├── `cleanliness-inspector.md` - File organization inspector for cleanup tasks. Detects misplaced docs, duplicates, temp files, build artifacts. Returns structured JSON report with cleanup recommendations.
│   ├── `dev.md` - Implementation specialist for development tasks. Receives rich JSON context from orchestrator, creates parameterized scripts, implements changes based on git root cause analysis. Returns structured execution report.
│   ├── `git-edge-case-analyst.md` - Git history analysis specialist. Discovers development edge cases by analyzing commits, violations, and patterns. Returns structured edge case report with prevention recommendations.
│   ├── `graphify.md` - Graphify enrichment subagent. Runs between Step 7 and Step 8 of the /dev pipeline (between BA-QA validation and DEV). Performs incremental Graphify cache update, extracts focused subgraph from BA blast-radius-map, patches context-<ts>.json with graph_context field, writes per-task artifacts to .claude/dev-registry/<task_id>/graphify/. Pure infrastructure agent — does NOT analyze requirements, make implementation decisions, write code, or interpret graph data for DEV.
│   ├── `merge-analyst.md` - Pre-merge analyst subagent. Inspects branch divergence, diff stat, conflict markers, and overnight-state consistency; writes a nonce-keyed merge-analyst grant (60s expiry) to /tmp/agentic-commit/merge-analyst/. Dispatched exclusively by /merge.
│   ├── `pm.md` - >-
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
│   ├── `allow.md` - Single-use break-glass — bypass all safety blocks for the next matching bash command this turn. /allow = anything; /allow --tool <pattern> = explicit pattern (regex auto-detected). Trailing tokens become an audit-log comment. Auto-expires at stop.
│   ├── `checkpoint.md` - Checkpoint Command
│   ├── `clean.md` - Aggressive project cleanup - normalize docs structure, archive everything, delete one-time scripts/tests. Pass --codex to enable adversarial codex consultation on cleanliness-inspector and style-inspector; default is self-review only.
│   ├── `close.md` - Close the current dev cycle (agent infers task-id from conversation). QA evaluates Workflow Integrity bullets and returns CLOSE YES/NO. Pass --codex to enable multi-round QA-codex debate; default is QA-only single-round assessment. Append --force to skip the debate entirely.
│   ├── `code-review.md` - Comprehensive code review with best practices analysis
│   ├── `codex.md` - Delegate a task to OpenAI Codex CLI (gpt-5.5, xhigh reasoning) for a second opinion or parallel coding
│   ├── `commit.md` - Commit session changes via changelog-analyst subagent
│   ├── `deep-search.md` - Deep website exploration with iterative search strategy
│   ├── `dev-command.md` - Enhanced development workflow with BA subagent delegation, command development best practices, Three-Party Architecture, and comprehensive automation patterns
│   ├── `dev-overnight.md` - Autonomous overnight development loop - continuously explores codebase, finds issues, fixes them, and repeats until end-time
│   ├── `dev.md` - Orchestrated development workflow with BA subagent delegation, parallel agent execution, and iterative QA verification. Pass --codex to enable adversarial codex consultation on each subagent's draft; default is self-review only.
│   ├── `do.md` - Allow main agent to bypass orchestrator-gate restrictions for this turn (subagent-only operations become directly allowed). Auto-clears at stop.
│   ├── `doc-gen.md` - Generate comprehensive documentation for code
│   ├── `doc-sync.md` - Regenerate all INDEX.md files and patch CLAUDE.md auto-sections
│   ├── `explain-code.md` - Deep explanation of code functionality and design
│   ├── `file-analyze.md` - Analyze PDF, Excel, Word, images and other files with deep insights
│   ├── `fswatch.md` - FSWatch Command
│   ├── `merge.md` - Merge the current overnight worktree branch into the default branch (agent infers branch from active overnight state). Bare /merge typical; explicit /merge <branch> overrides. Auto-cleans worktree + branch + overnight-state file when merge succeeds and the diff is clean.
│   ├── `optimize.md` - Analyze code for performance optimization opportunities
│   ├── `playwright-helper.md` - Guide for using Playwright MCP with deep search commands
│   ├── `pull.md` - Pull Command
│   ├── `push.md` - Push Command
│   ├── `quick-commit.md` - Create a well-formatted git commit with auto-generated message
│   ├── `quick-prototype.md` - Rapidly create interactive prototypes and demos combining multiple artifact capabilities
│   ├── `redev.md` - dev workflow, context-light invocation — same task semantics as /dev, but assumes the /dev workflow instructions are already loaded. Pass --codex to enable adversarial codex consultation on each subagent's draft; default is self-review only.
│   ├── `refactor.md` - Suggest refactoring improvements for code quality
│   ├── `reflect-search.md` - Reflection-driven iterative search with goal evaluation
│   ├── `research-deep.md` - Multi-source deep research with 15-20 iterative searches
│   ├── `search-tree.md` - Tree search exploration with MCTS-inspired path evaluation
│   ├── `security-check.md` - Security vulnerability analysis and recommendations
│   ├── `site-navigate.md` - Intelligent site navigation simulating "click-through" exploration
│   ├── `spec-update.md` - Continuation spec update or temp session note (was /update then /spec-continue — renamed to avoid collision with MAP's /update portfolio mutation command)
│   ├── `spec.md` - Create spec files for any dev workflow (/dev, /dev-overnight, or standalone reference). Pass --codex to enable adversarial codex consultation on each spec-subagent / QA dispatch; default is self-review only.
│   ├── `stop.md` - Cancel active overnight time-lock + workflow-enforce so the session can terminate normally. User-invoked only — agents cannot self-stop.
│   └── `test.md` - Test validation workflow with edge case detection, systematic validation, and quality enforcement
├── docs/
│   └── reference/
│       ├── `checkpoint-mechanism.md` - Auto-Commit / Checkpoint Mechanism
│       ├── `fswatch-quickref.md` - FSWatch 快速参考卡片
│       ├── `git-fswatch.md` - Git File Watcher (fswatch) 使用文档
│       ├── `graphify-integration.md` - Graphify Knowledge Graph Integration
│       ├── `lock-file-handling.md` - Git Lock File Handling
│       ├── `slashcommand-quick-reference.md` - Slash Command Quick Reference
│       ├── `tmp-cleanup-convention.md` - Ad-hoc scratch directory convention
│       └── `venv-repair.md` - venv-repair — restoring `~/.claude/venv` when interpreter symlinks break
├── hooks/
│   ├── doc_sync/
│   │   ├── `claude.py` - CLAUDE.md auto-creation and patching.
│   │   ├── `config.py` - Load doc-sync project-local config.
│   │   ├── `docker.py` - Parse docker-compose.yml and generate markdown table.
│   │   ├── `extract.py` - Extract description from various file types.
│   │   ├── `main.py` - Main entry point for doc-sync hook.
│   │   ├── `patch.py` - Patch CLAUDE.md dynamic sections using AUTO markers.
│   │   ├── `regen_index.py` - Regenerate INDEX.md for a directory.
│   │   ├── `regen_readme.py` - Regenerate README.md for a directory.
│   │   ├── `systemd.py` - Query systemctl for project-configured services and generate a markdown table.
│   │   └── `tree.py` - Build directory trees for INDEX.md.
│   ├── git-hooks/
│   │   ├── `post-commit-auto-push` - unknown file
│   │   └── `pre-commit` - unknown file
│   ├── git-keystone/
│   │   └── `reference-transaction` - unknown file
│   ├── lib/
│   │   ├── `agent_resolver.py` - Refactored from pretool-subagent-code-block.py::_find_agent_type so that
│   │   ├── `allowlist.py` - Single source of truth for grant-read, grant-match, and grant-consume
│   │   ├── `bash_context_strip.py` - This is deliberately NOT a full shell parser.  It only computes a conservative
│   │   ├── `bash_write_targets.py` - Provides two public functions used by tool-policy and overnight-hook-guard:
│   │   ├── `checkpoint-core.sh` - ============================================================================
│   │   ├── `close-verdict.py` - Shared CLOSE verdict classifier for commit/close tooling.
│   │   ├── `closeout.py` - Public API:
│   │   ├── `contract_runtime.py` - This module is the single shared engine consumed by every contract-aware
│   │   ├── `overnight.py` - Single source of truth for "is a /dev-overnight session currently live?". A
│   │   ├── `policy_registry.py` - Reads /root/.claude/policies/tool-policy.v1.json and provides a single
│   │   ├── `runtime_guard.py` - This module contains ZERO project identifiers. Every project-specific name
│   │   ├── `schema_registry.py` - Reads schemas/registry.json once and lazily loads referenced schema files
│   │   ├── `specialist_yield.py` - Public API:
│   │   ├── `subagent.py` - Single source of truth for is_subagent_context() and supporting helpers
│   │   └── `todo_canonical.py` - Shared canonical todo validation utilities
│   ├── tests/
│   │   ├── `test_ac10_verify.sh` - Shell script
│   │   ├── `test_ac1_verify.sh` - Shell script
│   │   ├── `test_ac3_verify.sh` - Shell script
│   │   ├── `test_ac5_verify.sh` - Shell script
│   │   ├── `test_ac6_verify.sh` - Shell script
│   │   ├── `test_ac9_verify.sh` - Shell script
│   │   ├── `test_allowlist_consolidation.py` - Covers AC8 IS_SUBAGENT firewall scenarios and matching semantics invariants
│   │   ├── `test_bash_safety_context.py` - Tests strip_non_executable_contexts() in isolation, covering the main
│   │   ├── `test_bash_safety_context_rules.py` - converted to COMMAND_CONTEXT_STRIPPED in hooks/pretool-bash-safety.sh
│   │   ├── `test_block_branch_pr_worktree.py` - The hook forbids branch / PR / worktree CREATION on the Bash surface, with three
│   │   ├── `test_bulk_commit_sentinel.py` - Covers:
│   │   ├── `test_commit_strip_dotfile_paths.py` - Bug surfaced cycle 20260511-100000: dev-report listed 6 `.claude/commands/*`
│   │   ├── `test_cp_checkin.py` - of ba-spec-20260427-194324.md (P1 view-trigger removal + P2 generation field)
│   │   ├── `test_do_taskid_mint.py` - Covers the root-cause fix for the do-report task-id collision (memory
│   │   ├── `test_final_sweep.sh` - Final sweep — run inline AC checks and print PASS/FAIL summary.
│   │   ├── `test_push_sentinel_abort.sh` - Unit test for AC1 V5: hooks/push.sh self-aborts before any real git push
│   │   └── `test_runtime_guard.py` - Two layers:
│   ├── `audit-slashcommand.sh` - audit-slashcommand.sh
│   ├── `auto-commit.sh` - ============================================================================
│   ├── `check-todo-md-sync.py` - check-todo-md-sync.py — Session-start drift detector for todo scripts
│   ├── `checkpoint.sh` - checkpoint.sh - Manual /checkpoint command
│   ├── `ensure-git-repo.sh` - ensure-git-repo.sh - DEPRECATED, scheduled for deletion
│   ├── `fswatch-manager.sh` - fswatch-manager.sh - Manage git-fswatch instances
│   ├── `git-fswatch.sh` - git-fswatch.sh - Comprehensive Git file watcher using fswatch
│   ├── `git-fswatch@.service` - service file
│   ├── `hook-todo-injection.py` - Global PreToolUse Hook: Todo Injection for Slash Commands
│   ├── `install-auto-sync.sh` - install-auto-sync.sh - Quick installer for auto-sync features
│   ├── `install-git-hooks.sh` - install-git-hooks.sh - Install pre-commit hooks into git repositories
│   ├── `install-protection-all.sh` - install-protection-all.sh - Automatically install protection for all git repos
│   ├── `install.sh` - ============================================================================
│   ├── `merge.sh` - merge.sh - wrapper for /merge slash command
│   ├── `notification-idle-overnight.py` - Notification hook: Observe overnight idle events
│   ├── `post-commit-warn.sh` - post-commit-warn.sh - Warn about untracked files after commit
│   ├── `post_tool_use.sh` - PostToolUse Hook - Code quality hints after file modifications
│   ├── `posttool-allowlist-consume.py` - PostToolUse Hook: /allow grant consumption
│   ├── `posttool-codex-skill-ledger.py` - Fires on every PostToolUse for the Skill tool. When tool_input.skill == "codex",
│   ├── `posttool-command-frontmatter-validate.py` - PostToolUse Hook: Validate .claude/commands/*.md frontmatter structure
│   ├── `posttool-doc-sync.py` - PostToolUse Hook: Auto-sync INDEX.md and CLAUDE.md when structural files change
│   ├── `posttool-git-checkpoint.sh` - posttool-git-checkpoint.sh - PostToolUse checkpoint trigger
│   ├── `posttool-git-warn.sh` - post-commit-warn.sh - Warn about untracked files after commit
│   ├── `posttool-overnight-file-check.py` - PostToolUse:Agent Hook — Contract-driven overnight file check
│   ├── `posttool-overnight-loop.py` - PostToolUse:TodoWrite Hook: Overnight Loop Detection
│   ├── `posttool-overnight-trace.py` - Writes one JSONL trace record per Agent invocation to:
│   ├── `posttool-runcode-watchdog.py` - PostToolUse Hook: Cancel timeout watchdog after browser_run_code completes
│   ├── `posttool-subagent-track.py` - PostToolUse:Agent Hook: Track subagent invocations in workflow bookmark
│   ├── `posttool-todo-count.py` - PostToolUse Hook: Enforce canonical todo count immediately after TodoWrite
│   ├── `posttool-todo-sequence.py` - PostToolUse Hook: Enforce one-step-at-a-time progression in workflow checklists
│   ├── `posttool-todo-tracker.py` - PostToolUse Hook: Output checklist progress after every TodoWrite call
│   ├── `pre-commit-check.sh` - pre-commit-check.sh - Detect untracked files before commit
│   ├── `pre_slashcommand_validate.sh` - pre_slashcommand_validate.sh
│   ├── `pre_tool_use_safety.sh` - PreToolUse Safety Hook - Warn before dangerous operations
│   ├── `pretool-aggregate-check.py` - existence before allowing the orchestrator to dispatch the QA subagent in
│   ├── `pretool-bash-safety.sh` - PreToolUse Safety Hook - Warn or block before dangerous operations
│   ├── `pretool-bash-views-guard.py` - Parallels pretool-bash-safety.sh but focuses on views/cp-state write bypass
│   ├── `pretool-bisect-gate.sh` - pretool-bisect-gate.sh
│   ├── `pretool-block-branch-pr-worktree.py` - Policy (user directive 2026-06-04; the verbatim user directive is preserved in
│   ├── `pretool-block-enterworktree.sh` - PreToolUse hook: Block EnterWorktree tool
│   ├── `pretool-bulk-commit-detector.py` - Write to stderr and exit 0 (warn-only per user policy: no text-smell hard-blocks).
│   ├── `pretool-claude-config-guard.py` - PreToolUse Hook: Claude config (.claude/hooks + .claude/commands) protection
│   ├── `pretool-cp-checkin.py` - cp-state file read
│   ├── `pretool-cp-state-write-guard.py` - Cycle-3 slim form (2026-05-14): Bash-extractor removed — 22-form adversarial
│   ├── `pretool-git-privilege-guard.py` - PreToolUse Hook: Agent git-privilege guard
│   ├── `pretool-gitignore-preflight.py` - pretool-gitignore-preflight.py — PreToolUse hook (matcher: Agent)
│   ├── `pretool-layer-escalation-check.sh` - pretool-layer-escalation-check.sh
│   ├── `pretool-layer-match-gate.sh` - pretool-layer-match-gate.sh
│   ├── `pretool-orchestrator-gate.py` - PreToolUse Hook: Orchestrator Gate (Unified)
│   ├── `pretool-orchestrator-prompt-purity.py` - PreToolUse hook: Orchestrator Prompt Purity
│   ├── `pretool-overnight-hook-guard.py` - PreToolUse Hook: Overnight session file modification guard
│   ├── `pretool-quality-gate.py` - PreToolUse Hook: Quality gate for Write/Edit operations
│   ├── `pretool-read-size-guard.py` - PreToolUse Hook: Read Size Guard
│   ├── `pretool-runcode-watchdog.py` - PreToolUse Hook: Start timeout watchdog for browser_run_code
│   ├── `pretool-spec-block-foreground-agent.py` - PreToolUse Hook: Block foreground Agent during an active /spec Interview
│   ├── `pretool-subagent-code-block.py` - Canonical enforcement: pretool-tool-policy.py + lib/policy_registry — this
│   ├── `pretool-subagent-enforce.py` - PreToolUse:Agent Hook — Contract-driven role/pipeline enforcement
│   ├── `pretool-todo-validate.py` - PreToolUse Hook: Validate TodoWrite input BEFORE execution
│   ├── `pretool-tool-policy.py` - Single hook that consumes /root/.claude/policies/tool-policy.v1.json via
│   ├── `pretool-workflow-gate.py` - PreToolUse Hook: Require TodoWrite/TodoRead acknowledgment before other tools
│   ├── `pretool-worktree-guard.sh` - PreToolUse hook: Detect stale agent worktrees before ANY tool call
│   ├── `pretool-wrapper-userintent.py` - fix-4 (Cycle-2, spec-20260604-204954 §7.4). The /stop slash command releases
│   ├── `pretool-write-guard.sh` - PreToolUse Hook - Block Write tool from overwriting existing files
│   ├── `project-settings-template.json` - json config
│   ├── `prompt-workflow.py` - UserPromptSubmit Hook: Checklist Injection for Slash Commands
│   ├── `protection-status.sh` - protection-status.sh - Display protection status for all git repositories
│   ├── `pull.sh` - pull.sh - Executable version of /pull command
│   ├── `QUICKSTART.md` - 🚀 Quick Start Guide
│   ├── `README-TODO-INJECTION.md` - Global Todo Injection Hook
│   ├── `sentinel-lint.sh` - sentinel-lint.sh - Guards the dev-registry sentinel anchor in orchestrator files
│   ├── `session-git-init.sh` - ============================================================================
│   ├── `session-gitignore-propagate.sh` - SessionStart hook: append missing standard harness gitignore rules to project repo
│   ├── `session-info.sh` - s-info.sh — SessionStart: display environment info + tool quick reference
│   ├── `session-promote-hook.sh` - Description: SessionStart hook that promotes a cold session back to ramdisk.
│   ├── `session-tmpfs-banner.sh` - session-tmpfs-banner.sh — SessionStart hook (6th in the SessionStart hooks block).
│   ├── `session_start.sh` - SessionStart Hook - Display working environment info
│   ├── `smart-checkpoint.sh` - smart-checkpoint.sh - DEPRECATED, scheduled for deletion
│   ├── `start-fswatch-all.sh` - start-fswatch-all.sh - Start fswatch monitoring for all important repositories
│   ├── `stop-cleanup-allowlist.sh` - Stop Hook: Wipe any unconsumed /allow grant at turn end.
│   ├── `stop-overnight-timelock.py` - Stop Hook: Block conversation termination until overnight end-time
│   ├── `stop-spec-coverage-enforce.py` - Stop Hook: Block spec agent from exiting with < 100% monolith coverage
│   ├── `stop.sh` - stop.sh - wrapper for /stop slash command
│   ├── `subagent-stop-diff-check.sh` - SubagentStop hook: flag large diffs without minimum-diff justification
│   ├── `subagent-stop-guard-integrity.sh` - subagent-stop-guard-integrity.sh
│   ├── `subagentstop-codex-enforce.py` - Activation logic:
│   ├── `subagentstop-cp-enforce.py` - Description: SubagentStop hook for spec checkpoint enforcement (W6).
│   ├── `subagentstop-e2e-enforce.py` - Activation logic:
│   ├── `userprompt-bulk-commit-capability.py` - human prompt, NOT from an LLM-emitted Bash command
│   ├── `userprompt-consent-allowlist.sh` - UserPromptSubmit Hook: parse `/allow <pattern>` and write a single-use
│   ├── `userprompt-doc-sync-check.py` - UserPromptSubmit Hook: Periodic file deletion detection for doc-sync
│   └── `userprompt-tmpfs-pressure.sh` - userprompt-tmpfs-pressure.sh — UserPromptSubmit hook (4th block, appended).
├── policies/
│   ├── `specialist-degradation.v1.json` - json config
│   └── `tool-policy.v1.json` - json config
├── schemas/
│   ├── `context.v1.json` - json config
│   ├── `cycle-contract.v1.json` - json config
│   ├── `dev-report.v1.json` - json config
│   ├── `graphify-focused-subgraph.v1.json` - json config
│   ├── `graphify-prequery.v1.json` - json config
│   ├── `graphify-run.v1.json` - json config
│   ├── `qa-report.v1.json` - json config
│   ├── `registry.json` - json config
│   └── `test-plan.v1.json` - json config
├── scripts/
│   ├── install/
│   │   └── `tmp-cleanup-install.sh` - /usr/local/sbin/tmp-cleanup.sh
│   ├── modern-git-slot/
│   ├── overnight-git/
│   │   ├── `git-policy-shim` - unknown file
│   │   └── `git-selector` - unknown file
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
│   │   ├── `do.py` - Injects the 4-step /do workflow checklist via hook-todo-injection
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
│   ├── `aggregate-dev-report.py` - Scans docs/dev/ for per-worker shard dev-reports matching a given task-id,
│   ├── `aggregate-permissions.py` - Usage: aggregate-permissions.py <qa-glob-or-dir> [pipelines.json]
│   ├── `analyze-folder-history.sh` - Description: Analyze Git history for folder to discover file creation patterns
│   ├── `analyze-git-edge-cases.sh` - Description: Analyze git history for edge cases from bug fix commits
│   ├── `apply-permissions.sh` - apply-permissions.sh — merge aggregated permissions JSON list into settings.json
│   ├── `blast-radius-tool.py` - Two phases:
│   ├── `break-overnight-lock.py` - Backdates end_time on every active overnight-state-*.json so
│   ├── `build-pipelines-from-triage.py` - Consumes PM triage schema (issues[] keyed by triage_index + pipeline_order[] +
│   ├── `canary-verify.sh` - Description: Cache-safe canary that behaviorally verifies the four core PreToolUse hooks.
│   ├── `check-file-references.sh` - File reference detection script - used by /clean command
│   ├── `check-overnight-reports.py` - Description: Validates all overnight required outputs declared by the active
│   ├── `check-overnight-reports.sh` - DEPRECATED — replaced by check-overnight-reports.py per spec-20260426-090235 P0/M5.
│   ├── `check-readme-freshness.sh` - Check README.md freshness for all major folders
│   ├── `check-security-hook-drift.sh` - Description: Audit always-on security-critical hook files against a cycle baseline SHA
│   ├── `checkpoint-prune.sh` - checkpoint-prune.sh — trim refs/checkpoints/* to the most recent N commits
│   ├── `cleanup-close-force-sentinel.sh` - Removes the force-close sentinel file for a given dev session.
│   ├── `cleanup-tests-folder.sh` - Description: Remove validators that don't match git edge cases, preserving reports/
│   ├── `close-scoring-decide.py` - Description: Decide which close_success_* event /close should issue based on
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
│   ├── `discover-folders.sh` - Description: Dynamically discover project folders excluding system directories
│   ├── `execute-push.py` - Eliminates the timing window that exists when validate + push are && -chained
│   ├── `generate-folder-index.sh` - Description: Generate INDEX.md for folder (inventory of contents)
│   ├── `generate-folder-readme.sh` - Description: Generate README.md for folder (purpose and organization rules)
│   ├── `graphify-enrich.py` - graphify-enrich.py — pre-DEV focused subgraph extractor (runs between Step 7 and Step 8)
│   ├── `graphify-maintain.py` - graphify-maintain.py — Global Graphify cache lifecycle manager (REAL CLI)
│   ├── `graphify-query.py` - graphify-query.py — deterministic pre-BA graph hydrator (runs between Step 1 and Step 2)
│   ├── `graphify_lib.py` - graphify_lib.py — shared library for Graphify knowledge-graph integration
│   ├── `install-checkpoint-refspec.sh` - install-checkpoint-refspec.sh — idempotently add refs/checkpoints/* to
│   ├── `install-git-keystone.sh` - install-git-keystone.sh — wire the git-native reference-transaction keystone
│   ├── `iterate-failed-pipelines.py` - Reads pipelines JSON path; outputs iteration plan JSON to stdout. The orchestrator
│   ├── `lifecycle-baseline-import.sh` - Description: One-time idempotent migration — import current agent scores from agent-scores.json
│   ├── `lint-spec-id-centralization.py` - markdown from re-deriving a spec-id / views_dir / split_marker / cp_dir from a
│   ├── `migrate-test-to-tests.sh` - Description: Merge test/ folder into tests/ preserving all content (idempotent)
│   ├── `mint-git-blessed-token.sh` - mint-git-blessed-token.sh — issuer of the keystone blessed token (M12).
│   ├── `normalize-doc-names.sh` - normalize-doc-names.sh - Detect and report non-compliant documentation file names
│   ├── `orchestrator.sh` - Description: Agent orchestration coordinator for development and cleanup workflows
│   ├── `overnight-git-env.sh` - overnight-git-env.sh — prepare the overnight actor's git PATH + env (M11/AC9).
│   ├── `overnight-git-selftest.sh` - overnight-git-selftest.sh — launch git-version + symref self-test (M8, M16).
│   ├── `overnight-status.sh` - overnight-status.sh — Zero-LLM overnight session status query
│   ├── `plan-style-inspection.sh` - Description: Discover auditable files and split into groups for parallel style inspection
│   ├── `precommitted-recovery.sh` - Description: Recovery path helpers for nothing_to_commit_precommitted detection.
│   ├── `qa-manifest-guard.py` - Dual-mode tool per BA spec docs/dev/ticket-20260529-081014.md M4:
│   ├── `qa-report-stale-iter-lint.py` - lacks an explicit resolution marker
│   ├── `refine-context.sh` - refine-context.sh — merge QA-refined context with original context
│   ├── `regen-index-dirs.py` - hand-written prose outside the generated stats+tree block), then regenerate the
│   ├── `repair-venv.sh` - repair-venv.sh — durably restore a Python venv when its bin/python3 symlink target is missing.
│   ├── `resolve-close-report.sh` - Resolve the close-report path for a given TASK_ID using subproject path-walk.
│   ├── `resolve-dev-report.py` - Usage:
│   ├── `resolve-spec-artifacts.py` - spec-id resolver shared by /spec finalize and every /dev* consumer)
│   ├── `runcode-watchdog.py` - Watchdog process for browser_run_code timeout enforcement
│   ├── `scan-project.sh` - Description: Scan project structure and detect project type
│   ├── `score-inject.sh` - Description: Emit a prompt-injection text block describing an agent's current rank/range
│   ├── `score-update.sh` - Description: Update agent score by appending an entry to the lifecycle JSONL log.
│   ├── `spec-check.py` - Subcommands: check-in, mark, waive, status, check-out, unlock
│   ├── `stage-owned-hunks.py` - Stages ONLY this cycle's owned hunks within a single already-authorized file,
│   ├── `step7-spec-update.py` - Step 8 (Spec-update dispatch) reference harness — task 20260524-205206 iter-2
│   ├── `update-gitignore.sh` - update-gitignore.sh - Auto-update .gitignore with project-specific rules
│   ├── `update-overnight-state.sh` - update-overnight-state.sh — Atomically update overnight state file
│   ├── `write-bulk-commit-sentinel.py` - Invoked from commands/commit.md Step 5 (BULK=true) to authorize the
│   ├── `write-codex-enforce.sh` - Writes codex-enforce.json into the dev-registry for the given session.
│   ├── `write-commit-grant.py` - Invoked from `commands/commit.md` Step 5 (non-bulk mode) to author a
│   ├── `write-e2e-enforce.sh` - Writes e2e-enforce.json into the dev-registry for the given session.
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
│   │   ├── `anti-pattern-catalog.yml` - yml config
│   │   ├── `report-schema.json` - json config
│   │   ├── `review-phases.yml` - yml config
│   │   └── `rule-map.json` - json config
│   ├── ui-state-matrix/
│   │   └── `SKILL.md` - Verify presence of 7 interactive states (default / hover / focus / active / disabled / loading / error / success) on key interactive elements. Returns deterministic state.* findings + state_coverage_pct + not_applicable[]. Use during ui-specialist Phase 4 (Interactive Element Visual Testing).
│   └── ui-token-conformance/
│       └── `SKILL.md` - Conditional capability — measure design-token conformance (color/spacing/typography) of computed CSS values against a project's declared token source (DTCG / tailwind.config.js / theme.ts). If no token source is detected, emit capability_unavailable to unknowns and DO NOT raise findings on guesses. Use during ui-specialist Phase 5 (Aesthetic).
├── templates/
│   ├── `overnight-spec.md` - Spec: <issue_description>
│   └── `spec-template.md` - Spec: <issue_description>
├── tests/
│   ├── cycle1-baseline-20260507-142952/
│   │   ├── `realpath_audit.py` - Audit realpath behavior in the guard for the codex finding.
│   │   ├── `run_ac1.py` - AC-1 verification: pretool-cp-state-write-guard.py.
│   │   ├── `run_ac1_v2.py` - AC-1 verification v2: pretool-cp-state-write-guard.py with correct fixture paths.
│   │   ├── `run_ac2.py` - AC-2 verification: subagentstop-cp-enforce.py orphan finalization.
│   │   ├── `run_ac3.py` - AC-3 verification: agent_resolver.py inactive cp-state non-authoritative + collision fail-closed.
│   │   ├── `setup_fixtures.py` - Create test fixtures via Python (Bash heredoc/echo to cp-state is blocked by hooks).
│   │   └── `symlink_test.py` - Test codex's symlink/realpath finding for AC-1 guard hook.
│   ├── generated/
│   │   ├── 20260520-221452/
│   │   ├── 20260521-090100/
│   │   ├── 20260521-090200/
│   │   ├── 20260521-090300/
│   │   ├── 20260522-000000/
│   │   ├── 20260522-080646-A/
│   │   ├── 20260522-080646-B/
│   │   ├── 20260522-080646-D/
│   │   ├── 20260524-122910/
│   │   ├── 20260524-122947/
│   │   ├── 20260524-125300-A/
│   │   ├── 20260524-125300-B/
│   │   ├── 20260524-125300-C/
│   │   ├── 20260524-125300-D/
│   │   ├── 20260524-125300-push/
│   │   ├── 20260524-133650/
│   │   ├── 20260524-171714/
│   │   ├── 20260524-172805/
│   │   ├── 20260524-205206/
│   │   ├── 20260524-205459/
│   │   ├── 20260525-050824/
│   │   ├── 20260525-095242/
│   │   ├── 20260526-052559/
│   │   ├── 20260526-053746/
│   │   ├── 20260527-132200/
│   │   ├── 20260529-080709/
│   │   ├── 20260529-081014/
│   │   ├── 20260529-210616/
│   │   ├── 20260529-211406/
│   │   ├── 20260530-105221/
│   │   ├── 20260530-165718/
│   │   ├── 20260530-170350/
│   │   ├── 20260531-112831-bug1/
│   │   ├── 20260611-100500/
│   │   ├── 20260614-093452/
│   │   ├── 20260614-205834/
│   │   ├── dev-20260530-144032/
│   │   ├── dev-20260531-134455/
│   │   ├── dev-20260531-193000/
│   │   └── `manifest.json` - json config
│   ├── instructions/
│   │   ├── `execution-guide.md` - AI Test Execution Guide
│   │   └── `validation-guide.md` - AI-Driven Validation Guide
│   ├── reports/
│   │   ├── `completion-test-20260107-104018.md` - Test Execution Completion Report
│   │   ├── `edge-case-analysis.json` - json config
│   │   ├── `execution-report-test-20260107-095503.json` - json config
│   │   └── `execution-report-test-20260107-104018.json` - json config
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
│   ├── `integration-test.sh` - integration-test.sh - Integration tests for git tracking solution
│   ├── `test-lock-detection.sh` - Test script to verify git lock file detection and handling
│   ├── `test_aggregate_dev_report.py` - Unit tests for scripts/aggregate-dev-report.py
│   ├── `test_graphify_scripts.py` - tests/test_graphify_scripts.py — smoke tests for scripts/graphify_lib.py
│   ├── `test_graphify_workflow_contract.py` - tests/test_graphify_workflow_contract.py — contract tests for graphify agent registration
│   ├── `test_overnight_loop_tz.py` - Verifies the overnight loop hook compares end_time correctly against the
│   ├── `test_resolve_spec_artifacts.py` - resolver) + the static centralization lint (AC-B4 cases 1-12, task 20260530-092123)
│   ├── `test_specialist_yield.py` - Tests use a tmp dir for the yield log and the bundled production policy file
│   └── `verify-stop-spec-session-isolation.sh` - QA verification harness for stop-spec-coverage-enforce.py session isolation fix.
├── `ARCHITECTURE.md` - Architecture — `.claude` Agent Operating System
├── `CLAUDE.md` - CLAUDE.md
├── `LICENSE` - unknown file
├── `NESTED-REPO.md` - Nested Repo Sentinel
├── `NOTICE` - unknown file
└── `settings.json` - json config
```
<!-- /AUTO:index-stats -->

# .claude


# dot-claude


# .claude


# dot-claude


# .claude

---
*Auto-generated by doc-sync hook.*
