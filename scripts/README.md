# scripts

Organization and usage documentation for `scripts/`.

<!-- AUTO:readme-stats -->

## Overview
- **Total files**: 72
- **Subdirectories**: 4
- **Naming convention**: kebab

## Files
- `aggregate-dev-report.py` - Scans docs/dev/ for per-worker shard dev-reports matching a given task-id,
- `aggregate-permissions.py` - Usage: aggregate-permissions.py <qa-glob-or-dir> [pipelines.json]
- `analyze-folder-history.sh` - Description: Analyze Git history for folder to discover file creation patterns
- `analyze-git-edge-cases.sh` - Description: Analyze git history for edge cases from bug fix commits
- `apply-permissions.sh` - apply-permissions.sh — merge aggregated permissions JSON list into settings.json
- `blast-radius-tool.py` - Two phases:
- `break-overnight-lock.py` - Backdates end_time on every active overnight-state-*.json so
- `build-pipelines-from-triage.py` - Consumes PM triage schema (issues[] keyed by triage_index + pipeline_order[] +
- `canary-verify.sh` - Description: Cache-safe canary that behaviorally verifies the four core PreToolUse hooks.
- `check-file-references.sh` - File reference detection script - used by /clean command
- `check-overnight-reports.py` - Description: Validates all overnight required outputs declared by the active
- `check-overnight-reports.sh` - DEPRECATED — replaced by check-overnight-reports.py per spec-20260426-090235 P0/M5.
- `check-readme-freshness.sh` - Check README.md freshness for all major folders
- `check-security-hook-drift.sh` - Description: Audit always-on security-critical hook files against a cycle baseline SHA
- `checkpoint-prune.sh` - checkpoint-prune.sh — trim refs/checkpoints/* to the most recent N commits
- `cleanup-close-force-sentinel.sh` - Removes the force-close sentinel file for a given dev session.
- `cleanup-tests-folder.sh` - Description: Remove validators that don't match git edge cases, preserving reports/
- `close-scoring-decide.py` - Description: Decide which close_success_* event /close should issue based on
- `create-overnight-state.sh` - create-overnight-state.sh — Create overnight state file (v7 schema)
- `create-worktree.sh` - Create a git worktree from local HEAD (not origin/main).
- `derive-default-branch.sh` - Description: Resolve the repository's default branch name dynamically (handles main/master/any other).
- `detect-dead-functions.sh` - Shell script
- `detect-duplicate-content.sh` - Shell script
- `detect-hardcoded-paths.sh` - Shell script
- `detect-merge-conflicts.sh` - Shell script
- `detect-orphan-agents.sh` - Description: Detect agents not referenced by any command
- `detect-orphan-commands.sh` - Description: Detect orphan commands (one-time patterns, no todo script, unused)
- `detect-orphan-scripts.sh` - Description: Detect scripts not referenced by any command/agent/other script
- `discover-folders.sh` - Description: Dynamically discover project folders excluding system directories
- `execute-push.py` - Eliminates the timing window that exists when validate + push are && -chained
- `generate-folder-index.sh` - Description: Generate INDEX.md for folder (inventory of contents)
- `generate-folder-readme.sh` - Description: Generate README.md for folder (purpose and organization rules)
- `graphify-enrich.py` - graphify-enrich.py — pre-DEV focused subgraph extractor (runs between Step 7 and Step 8)
- `graphify-maintain.py` - graphify-maintain.py — Global Graphify cache lifecycle manager (REAL CLI)
- `graphify-query.py` - graphify-query.py — deterministic pre-BA graph hydrator (runs between Step 1 and Step 2)
- `graphify_lib.py` - graphify_lib.py — shared library for Graphify knowledge-graph integration
- `install-checkpoint-refspec.sh` - install-checkpoint-refspec.sh — idempotently add refs/checkpoints/* to
- `iterate-failed-pipelines.py` - Reads pipelines JSON path; outputs iteration plan JSON to stdout. The orchestrator
- `lifecycle-baseline-import.sh` - Description: One-time idempotent migration — import current agent scores from agent-scores.json
- `lint-spec-id-centralization.py` - markdown from re-deriving a spec-id / views_dir / split_marker / cp_dir from a
- `migrate-test-to-tests.sh` - Description: Merge test/ folder into tests/ preserving all content (idempotent)
- `normalize-doc-names.sh` - normalize-doc-names.sh - Detect and report non-compliant documentation file names
- `orchestrator.sh` - Description: Agent orchestration coordinator for development and cleanup workflows
- `overnight-status.sh` - overnight-status.sh — Zero-LLM overnight session status query
- `plan-style-inspection.sh` - Description: Discover auditable files and split into groups for parallel style inspection
- `precommitted-recovery.sh` - Description: Recovery path helpers for nothing_to_commit_precommitted detection.
- `qa-manifest-guard.py` - Dual-mode tool per BA spec docs/dev/ticket-20260529-081014.md M4:
- `qa-report-stale-iter-lint.py` - lacks an explicit resolution marker
- `quick-excel` - unknown file
- `refine-context.sh` - refine-context.sh — merge QA-refined context with original context
- `repair-venv.sh` - repair-venv.sh — durably restore a Python venv when its bin/python3 symlink target is missing.
- `resolve-close-report.sh` - Resolve the close-report path for a given TASK_ID using subproject path-walk.
- `resolve-dev-report.py` - Usage:
- `resolve-spec-artifacts.py` - spec-id resolver shared by /spec finalize and every /dev* consumer)
- `runcode-watchdog.py` - Watchdog process for browser_run_code timeout enforcement
- `scan-project.sh` - Description: Scan project structure and detect project type
- `score-inject.sh` - Description: Emit a prompt-injection text block describing an agent's current rank/range
- `score-update.sh` - Description: Update agent score by appending an entry to the lifecycle JSONL log.
- `spec-check.py` - Subcommands: check-in, mark, waive, status, check-out, unlock
- `stage-owned-hunks.py` - Stages ONLY this cycle's owned hunks within a single already-authorized file,
- `step7-spec-update.py` - Step 8 (Spec-update dispatch) reference harness — task 20260524-205206 iter-2
- `update-gitignore.sh` - update-gitignore.sh - Auto-update .gitignore with project-specific rules
- `update-overnight-state.sh` - update-overnight-state.sh — Atomically update overnight state file
- `write-bulk-commit-sentinel.py` - Invoked from commands/commit.md Step 5 (BULK=true) to authorize the
- `write-codex-enforce.sh` - Writes codex-enforce.json into the dev-registry for the given session.
- `write-commit-grant.py` - Invoked from `commands/commit.md` Step 5 (non-bulk mode) to author a
- `write-e2e-enforce.sh` - Writes e2e-enforce.json into the dev-registry for the given session.
- `write-qa-mode.sh` - Write or update qa_mode field in the QA sentinel file for a dev-registry session.

## Subdirectories
- `install/`
- `spec-verify/`
- `todo/`

---
*Auto-generated by doc-sync hook.*
<!-- /AUTO:readme-stats -->

---

*Auto-generated by doc-sync hook. Manual edits outside AUTO markers are preserved.*
