# hooks

<!-- AUTO:index-stats -->
*Last updated: 2026-07-16T15:41:22Z*
**Total entries**: 157
**Convention**: kebab

## Tree
```
hooks/
├── doc_sync/
│   ├── `claude.py` - CLAUDE.md auto-creation and patching.
│   ├── `config.py` - The git-tracked helpers (WS5, AC-WS5-1) let the INDEX/README generators list
│   ├── `docker.py` - Parse docker-compose.yml and generate markdown table.
│   ├── `extract.py` - Extract description from various file types.
│   ├── `main.py` - Main entry point for doc-sync hook.
│   ├── `patch.py` - Patch CLAUDE.md dynamic sections using AUTO markers.
│   ├── `regen_index.py` - Regenerate INDEX.md for a directory.
│   ├── `regen_readme.py` - Regenerate README.md for a directory.
│   ├── `systemd.py` - Query systemctl for project-configured services and generate a markdown table.
│   └── `tree.py` - Build directory trees for INDEX.md.
├── git-hooks/
│   ├── `post-commit-auto-push` - post-commit-auto-push file
│   └── `pre-commit` - pre-commit file
├── git-keystone/
│   └── `reference-transaction` - reference-transaction file
├── lib/
│   ├── runtime_guard/
│   │   ├── `__main__.py` - Package entry-point so `python -m lib.runtime_guard` still works.
│   │   ├── `_core.py` - This module contains ZERO project identifiers. Every project-specific name
│   │   ├── `anchor.py` - The cleanly-extractable leaf subset of the HEAD-AGNOSTIC P0 anchor scan
│   │   ├── `config.py` - Depends on shell_lex (`_strip_quotes`, `_has_redirect_to`) + pathmatch
│   │   ├── `constants.py` - Dependency LEAF: defines only literal frozenset/dict constants, imports nothing,
│   │   ├── `find_cmds.py` - Depends on shell_lex (`_strip_quotes`) + pathmatch (`_glob_to_segment_regex`,
│   │   ├── `git_cmds.py` - Depends on shell_lex (`_strip_quotes`) + pathmatch (`_expand_leading_home`) +
│   │   ├── `pathmatch.py` - Depends only on shell_lex (`_strip_quotes`) + stdlib; references nothing from
│   │   └── `shell_lex.py` - Dependency LEAF: imports only the stdlib, references nothing from _core
│   ├── `agent_resolver.py` - Refactored from pretool-subagent-code-block.py::_find_agent_type so that
│   ├── `allowlist.py` - Single source of truth for grant-read, grant-match, and grant-consume
│   ├── `bash_context_strip.py` - This is deliberately NOT a full shell parser.  It only computes a conservative
│   ├── `bash_write_targets.py` - Provides two public functions used by tool-policy and overnight-hook-guard:
│   ├── `checkpoint-core.sh` - checkpoint-core.sh - Shared library for automated snapshot commits
│   ├── `claude_home.py` - Generalizes the in-repo gold-standard fail-closed self-resolution pattern
│   ├── `claude_home.sh` - claude_home.sh — shared "harness home" resolver (shell consumable).
│   ├── `close-verdict.py` - Shared CLOSE verdict classifier for commit/close tooling.
│   ├── `closeout.py` - Public API:
│   ├── `contract_runtime.py` - This module is the single shared engine consumed by every contract-aware
│   ├── `git_command_classifier.py` - Provides iter_git_invocations() — a token-aware parser that detects git
│   ├── `grepguard_context_strip.py` - PURPOSE (narrow, guard-specific)
│   ├── `overnight.py` - Single source of truth for "is a /dev-overnight session currently live?". A
│   ├── `policy_registry.py` - Reads the harness ``policies/tool-policy.v1.json`` (resolved via the shared
│   ├── `runtime_guard.py` - This file exists for backwards-compatibility with callers that invoke
│   ├── `schema_registry.py` - Reads schemas/registry.json once and lazily loads referenced schema files
│   ├── `specialist_yield.py` - Public API:
│   ├── `subagent.py` - Single source of truth for is_subagent_context() and supporting helpers
│   └── `todo_canonical.py` - Shared canonical todo validation utilities
├── tests/
│   ├── `test_ac10_verify.sh` - Shell script
│   ├── `test_ac1_verify.sh` - Shell script
│   ├── `test_ac3_verify.sh` - Shell script
│   ├── `test_ac5_verify.sh` - Shell script
│   ├── `test_ac6_verify.sh` - Shell script
│   ├── `test_ac9_verify.sh` - Shell script
│   ├── `test_allowlist_consolidation.py` - Covers AC8 IS_SUBAGENT firewall scenarios and matching semantics invariants
│   ├── `test_bash_safety_context.py` - Tests strip_non_executable_contexts() in isolation, covering the main
│   ├── `test_bash_safety_context_rules.py` - converted to COMMAND_CONTEXT_STRIPPED in hooks/pretool-bash-safety.sh
│   ├── `test_block_branch_pr_worktree.py` - The hook forbids branch / PR / worktree CREATION on the Bash surface, with three
│   ├── `test_bulk_commit_sentinel.py` - Covers:
│   ├── `test_cp_checkin.py` - of ba-spec-20260427-194324.md (P1 view-trigger removal + P2 generation field)
│   ├── `test_do_taskid_mint.py` - Covers the root-cause fix for the do-report task-id collision (memory
│   ├── `test_extract.py` - Unit tests for hooks/doc_sync/extract.py — covers all 4 defects + known-file cases.
│   ├── `test_final_sweep.sh` - Final sweep — run inline AC checks and print PASS/FAIL summary.
│   ├── `test_git_cmd_cross_consistency.py` - Verifies that GIT_CMD_RE (hooks/pretool-bash-safety.sh),
│   ├── `test_push_sentinel_abort.sh` - Unit test for AC1 V5: hooks/push.sh self-aborts before any real git push
│   ├── `test_runtime_guard.py` - Two layers:
├── `audit-slashcommand.sh` - audit-slashcommand.sh
├── `auto-commit.sh` - auto-commit.sh - Stop hook: snapshot on conversation end
├── `check-todo-md-sync.py` - check-todo-md-sync.py — Session-start drift detector for todo scripts
├── `checkpoint.sh` - checkpoint.sh - Manual /checkpoint command
├── `fswatch-manager.sh` - fswatch-manager.sh - Manage git-fswatch instances
├── `git-fswatch.sh` - git-fswatch.sh - Comprehensive Git file watcher using fswatch
├── `git-fswatch@.service` - service file
├── `hook-todo-injection.py` - Global PreToolUse Hook: Todo Injection for Slash Commands
├── `install-auto-sync.sh` - LEGACY / DO NOT USE — describes an obsolete auto-sync model.
├── `install-git-hooks.sh` - LEGACY / DO NOT USE — describes an obsolete git-tracking model.
├── `install-protection-all.sh` - LEGACY / DO NOT USE — describes an obsolete auto-push protection model.
├── `install.sh` - LEGACY / DO NOT USE — describes an obsolete auto-commit model.
├── `merge.sh` - merge.sh - wrapper for /merge slash command
├── `notification-idle-overnight.py` - Notification hook: Observe overnight idle events
├── `post-commit-warn.sh` - post-commit-warn.sh - Warn about untracked files after commit
├── `post_tool_use.sh` - PostToolUse Hook - Code quality hints after file modifications
├── `posttool-allowlist-consume.py` - PostToolUse Hook: /allow grant consumption
├── `posttool-codex-skill-ledger.py` - Fires on every PostToolUse for the Skill tool. When tool_input.skill == "codex",
├── `posttool-command-frontmatter-validate.py` - PostToolUse Hook: Validate .claude/commands/*.md frontmatter structure
├── `posttool-doc-sync.py` - PostToolUse Hook: Auto-sync INDEX.md and CLAUDE.md when structural files change
├── `posttool-git-checkpoint.sh` - posttool-git-checkpoint.sh - PostToolUse checkpoint trigger
├── `posttool-git-warn.sh` - post-commit-warn.sh - Warn about untracked files after commit
├── `posttool-overnight-file-check.py` - PostToolUse:Agent Hook — Contract-driven overnight file check
├── `posttool-overnight-loop.py` - PostToolUse:TodoWrite Hook: Overnight Loop Detection
├── `posttool-overnight-trace.py` - Writes one JSONL trace record per Agent invocation to:
├── `posttool-runcode-watchdog.py` - PostToolUse Hook: Cancel timeout watchdog after browser_run_code completes
├── `posttool-subagent-track.py` - PostToolUse:Agent Hook: Track subagent invocations in workflow bookmark
├── `posttool-todo-count.py` - PostToolUse Hook: Enforce canonical todo count immediately after TodoWrite
├── `posttool-todo-sequence.py` - PostToolUse Hook: Enforce one-step-at-a-time progression in workflow checklists
├── `posttool-todo-tracker.py` - PostToolUse Hook: Output checklist progress after every TodoWrite call
├── `pre-commit-check.sh` - pre-commit-check.sh - Detect untracked files before commit
├── `pre_slashcommand_validate.sh` - pre_slashcommand_validate.sh
├── `pre_tool_use_safety.sh` - PreToolUse Safety Hook - Warn before dangerous operations
├── `pretool-aggregate-check.py` - existence before allowing the orchestrator to dispatch the QA subagent in
├── `pretool-bash-safety.sh` - PreToolUse Safety Hook - Warn or block before dangerous operations
├── `pretool-bash-views-guard.py` - Parallels pretool-bash-safety.sh but focuses on views/cp-state write bypass
├── `pretool-bisect-gate.sh` - pretool-bisect-gate.sh
├── `pretool-block-background-tasks.py` - PreToolUse hook: block background execution on Agent/Task/Bash/SendMessage/Workflow
├── `pretool-block-branch-pr-worktree.py` - Policy (user directive 2026-06-04; the verbatim user directive is preserved in
├── `pretool-block-enterworktree.sh` - PreToolUse hook: Block EnterWorktree tool
├── `pretool-bulk-commit-detector.py` - PreToolUse Hook: Bulk-commit detector
├── `pretool-claude-config-guard.py` - PreToolUse Hook: Claude config (.claude/hooks + .claude/commands) protection
├── `pretool-cp-checkin.py` - cp-state file read
├── `pretool-cp-state-write-guard.py` - Cycle-3 slim form (2026-05-14): Bash-extractor removed — 22-form adversarial
├── `pretool-git-privilege-guard.py` - PreToolUse Hook: Agent git-privilege guard
├── `pretool-gitignore-preflight.py` - pretool-gitignore-preflight.py — PreToolUse hook (matcher: Agent)
├── `pretool-grep-backtrack-guard.py` - ROOT-CAUSE BACKGROUND (verified ground truth, 2026-06-15 host OOM)
├── `pretool-layer-escalation-check.sh` - pretool-layer-escalation-check.sh
├── `pretool-layer-match-gate.sh` - pretool-layer-match-gate.sh
├── `pretool-orchestrator-gate.py` - PreToolUse Hook: Orchestrator Gate (Unified)
├── `pretool-orchestrator-prompt-purity.py` - PreToolUse hook: Orchestrator Prompt Purity
├── `pretool-overnight-hook-guard.py` - PreToolUse Hook: Overnight session file modification guard
├── `pretool-quality-gate.py` - PreToolUse Hook: Quality gate for Write/Edit operations
├── `pretool-read-size-guard.py` - PreToolUse Hook: Read Size Guard
├── `pretool-runcode-watchdog.py` - PreToolUse Hook: Start timeout watchdog for browser_run_code
├── `pretool-spec-block-foreground-agent.py` - PreToolUse Hook: Block foreground Agent during an active /spec Interview
├── `pretool-subagent-code-block.py` - Canonical enforcement: pretool-tool-policy.py + lib/policy_registry — this
├── `pretool-subagent-enforce.py` - PreToolUse:Agent Hook — Contract-driven role/pipeline enforcement
├── `pretool-todo-validate.py` - PreToolUse Hook: Validate TodoWrite input BEFORE execution
├── `pretool-tool-policy.py` - Single hook that consumes the harness ``policies/tool-policy.v1.json`` (resolved
├── `pretool-workflow-gate.py` - PreToolUse Hook: Require TodoWrite/TodoRead acknowledgment before other tools
├── `pretool-worktree-guard.sh` - PreToolUse hook: Detect stale agent worktrees before ANY tool call
├── `pretool-wrapper-userintent.py` - fix-4 (Cycle-2, spec-20260604-204954 §7.4). The /stop slash command releases
├── `pretool-write-guard.sh` - PreToolUse Hook - Block Write tool from overwriting existing files
├── `project-settings-template.json` - JSON config: $schema, comment, comment_usage, hooks, permissions
├── `prompt-workflow.py` - UserPromptSubmit Hook: Checklist Injection for Slash Commands
├── `protection-status.sh` - protection-status.sh - Display protection status for all git repositories
├── `pull.sh` - pull.sh - Executable version of /pull command
├── `push.sh` - push.sh - Executable version of /push command
├── `QUICKSTART.md` - Quick Start — the hooks layer
├── `README-TODO-INJECTION.md` - Global Todo Injection Hook
├── `sentinel-lint.sh` - sentinel-lint.sh - Guards the dev-registry sentinel anchor in orchestrator files
├── `session-git-init.sh` - Ensure Git Repository Hook for Claude Code
├── `session-gitignore-propagate.sh` - SessionStart hook: append missing standard harness gitignore rules to project repo
├── `session-info.sh` - s-info.sh — SessionStart: display environment info + tool quick reference
├── `session-promote-hook.sh` - Description: SessionStart hook that promotes a cold session back to ramdisk.
├── `session-tmpfs-banner.sh` - session-tmpfs-banner.sh — SessionStart hook (6th in the SessionStart hooks block).
├── `session_start.sh` - SessionStart Hook - Display working environment info
├── `start-fswatch-all.sh` - start-fswatch-all.sh - Start fswatch monitoring for all important repositories
├── `stop-cleanup-allowlist.sh` - Stop Hook: Wipe any unconsumed /allow grant at turn end.
├── `stop-overnight-timelock.py` - Stop Hook: Block conversation termination until overnight end-time
├── `stop-spec-coverage-enforce.py` - Stop Hook: Block spec agent from exiting with < 100% monolith coverage
├── `stop.sh` - stop.sh - wrapper for /stop slash command
├── `subagent-stop-diff-check.sh` - SubagentStop hook: flag large diffs without minimum-diff justification
├── `subagent-stop-guard-integrity.sh` - subagent-stop-guard-integrity.sh
├── `subagentstop-codex-enforce.py` - Activation logic:
├── `subagentstop-cp-enforce.py` - Description: SubagentStop hook for spec checkpoint enforcement (W6).
├── `subagentstop-e2e-enforce.py` - Activation logic:
├── `userprompt-bulk-commit-capability.py` - human prompt, NOT from an LLM-emitted Bash command
├── `userprompt-consent-allowlist.sh` - UserPromptSubmit Hook: parse `/allow <pattern>` and write a single-use
├── `userprompt-doc-sync-check.py` - UserPromptSubmit Hook: Periodic file deletion detection for doc-sync
└── `userprompt-tmpfs-pressure.sh` - userprompt-tmpfs-pressure.sh — UserPromptSubmit hook (4th block, appended).
```
<!-- /AUTO:index-stats -->

---
*Auto-generated by doc-sync hook.*