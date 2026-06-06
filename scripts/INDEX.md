# scripts

<!-- AUTO:index-stats -->
*Last updated: 2026-06-06T12:32:02Z*
**Total entries**: 101
**Convention**: kebab

## Tree
```
scripts/
├── install/
│   └── `tmp-cleanup-install.sh` - /usr/local/sbin/tmp-cleanup.sh
├── spec-verify/
│   ├── `spec-verify-views.py` - Usage:
│   ├── `spec-verify.py` - Every non-blank, non-separator line from the monolith must appear
│   ├── `spec_verify_gated.py` - Three sibling checks that share the T5 ``is_strict_guide_mode`` gate and
│   ├── `spec_verify_mandate.py` - Activated only when the monolith declares ``guide_version: 1`` (or higher)
│   ├── `spec_verify_parsers.py` - Authoritative grammar: /root/docs/dev/specs/MONOLITH-WRITING-GUIDE.md R6.6
│   └── `spec_verify_summary.py` - Lives alongside `spec_verify_parsers.py` as a sibling sidecar because
├── todo/
│   ├── `clean.py` - Preloaded TodoList for /clean workflow
│   ├── `close.py` - Three user-visible TodoSteps (flat-integer per agents/style-inspector.md
│   ├── `code-review.py` - Python script
│   ├── `deep-search.py` - Python script
│   ├── `dev-command.py` - This todo script generates workflow steps for the BA-delegated dev-command workflow
│   ├── `dev-overnight.py` - Preloaded TodoList for /dev-overnight workflow
│   ├── `dev.py` - Preloaded TodoList for /dev workflow
│   ├── `do.py` - Injects the 4-step /do workflow checklist via hook-todo-injection
│   ├── `doc-gen.py` - Python script
│   ├── `explain-code.py` - Python script
│   ├── `file-analyze.py` - Preloaded TodoList for /file-analyze workflow
│   ├── `optimize.py` - Python script
│   ├── `playwright-helper.py` - Python script
│   ├── `quick-prototype.py` - Preloaded TodoList for /quick-prototype workflow
│   ├── `redev.py` - Preloaded TodoList for /redev workflow. Delegates to dev.py (single source of truth).
│   ├── `refactor.py` - Python script
│   ├── `reflect-search.py` - Preloaded TodoList for /reflect-search workflow
│   ├── `research-deep.py` - Python script
│   ├── `security-check.py` - Python script
│   ├── `site-navigate.py` - Python script
│   ├── `spec.py` - Mirrors the ask.py structure in the knowledge-system scripts/todo directory
│   └── `test.py` - Preloaded TodoList for /test workflow
├── `aggregate-dev-report.py` - Scans docs/dev/ for per-worker shard dev-reports matching a given task-id,
├── `aggregate-permissions.py` - Usage: aggregate-permissions.py <qa-glob-or-dir> [pipelines.json]
├── `analyze-folder-history.sh` - Description: Analyze Git history for folder to discover file creation patterns
├── `analyze-git-edge-cases.sh` - Description: Analyze git history for edge cases from bug fix commits
├── `apply-permissions.sh` - apply-permissions.sh — merge aggregated permissions JSON list into settings.json
├── `blast-radius-tool.py` - Two phases:
├── `break-overnight-lock.py` - Backdates end_time on every active overnight-state-*.json so
├── `build-pipelines-from-triage.py` - Consumes PM triage schema (issues[] keyed by triage_index + pipeline_order[] +
├── `bulk-commit-nested-run.sh` - One-shot bulk commit script for the nested dot-claude repo.
├── `canary-verify.sh` - Description: Cache-safe canary that behaviorally verifies the four core PreToolUse hooks.
├── `check-file-references.sh` - File reference detection script - used by /clean command
├── `check-overnight-reports.py` - Description: Validates all overnight required outputs declared by the active
├── `check-overnight-reports.sh` - DEPRECATED — replaced by check-overnight-reports.py per spec-20260426-090235 P0/M5.
├── `check-readme-freshness.sh` - Check README.md freshness for all major folders
├── `check-security-hook-drift.sh` - Description: Audit always-on security-critical hook files against a cycle baseline SHA
├── `checkpoint-prune.sh` - checkpoint-prune.sh — trim refs/checkpoints/* to the most recent N commits
├── `cleanup-close-force-sentinel.sh` - Removes the force-close sentinel file for a given dev session.
├── `cleanup-tests-folder.sh` - Description: Remove validators that don't match git edge cases, preserving reports/
├── `close-scoring-decide.py` - Description: Decide which close_success_* event /close should issue based on
├── `create-overnight-state.sh` - create-overnight-state.sh — Create overnight state file (v7 schema)
├── `create-worktree.sh` - Create a git worktree from local HEAD (not origin/main).
├── `derive-default-branch.sh` - Description: Resolve the repository's default branch name dynamically (handles main/master/any other).
├── `detect-dead-functions.sh` - Shell script
├── `detect-duplicate-content.sh` - Shell script
├── `detect-hardcoded-paths.sh` - Shell script
├── `detect-merge-conflicts.sh` - Shell script
├── `detect-orphan-agents.sh` - Description: Detect agents not referenced by any command
├── `detect-orphan-commands.sh` - Description: Detect orphan commands (one-time patterns, no todo script, unused)
├── `detect-orphan-scripts.sh` - Description: Detect scripts not referenced by any command/agent/other script
├── `discover-folders.sh` - Description: Dynamically discover project folders excluding system directories
├── `execute-push.py` - Eliminates the timing window that exists when validate + push are && -chained
├── `generate-folder-index.sh` - Description: Generate INDEX.md for folder (inventory of contents)
├── `generate-folder-readme.sh` - Description: Generate README.md for folder (purpose and organization rules)
├── `graphify-enrich.py` - graphify-enrich.py — pre-DEV focused subgraph extractor (runs between Step 7 and Step 8)
├── `graphify-maintain.py` - graphify-maintain.py — Global Graphify cache lifecycle manager (REAL CLI)
├── `graphify-query.py` - graphify-query.py — deterministic pre-BA graph hydrator (runs between Step 1 and Step 2)
├── `graphify_lib.py` - graphify_lib.py — shared library for Graphify knowledge-graph integration
├── `install-checkpoint-refspec.sh` - install-checkpoint-refspec.sh — idempotently add refs/checkpoints/* to
├── `iterate-failed-pipelines.py` - Reads pipelines JSON path; outputs iteration plan JSON to stdout. The orchestrator
├── `lifecycle-baseline-import.sh` - Description: One-time idempotent migration — import current agent scores from agent-scores.json
├── `lint-spec-id-centralization.py` - markdown from re-deriving a spec-id / views_dir / split_marker / cp_dir from a
├── `migrate-test-to-tests.sh` - Description: Merge test/ folder into tests/ preserving all content (idempotent)
├── `normalize-doc-names.sh` - normalize-doc-names.sh - Detect and report non-compliant documentation file names
├── `orchestrator.sh` - Description: Agent orchestration coordinator for development and cleanup workflows
├── `overnight-status.sh` - overnight-status.sh — Zero-LLM overnight session status query
├── `plan-style-inspection.sh` - Description: Discover auditable files and split into groups for parallel style inspection
├── `precommitted-recovery.sh` - Description: Recovery path helpers for nothing_to_commit_precommitted detection.
├── `qa-manifest-guard.py` - Dual-mode tool per BA spec docs/dev/ticket-20260529-081014.md M4:
├── `qa-report-stale-iter-lint.py` - lacks an explicit resolution marker
├── `quick-excel` - unknown file
├── `refine-context.sh` - refine-context.sh — merge QA-refined context with original context
├── `repair-venv.sh` - repair-venv.sh — durably restore a Python venv when its bin/python3 symlink target is missing.
├── `resolve-close-report.sh` - Resolve the close-report path for a given TASK_ID using subproject path-walk.
├── `resolve-dev-report.py` - Usage:
├── `resolve-spec-artifacts.py` - spec-id resolver shared by /spec finalize and every /dev* consumer)
├── `runcode-watchdog.py` - Watchdog process for browser_run_code timeout enforcement
├── `scan-project.sh` - Description: Scan project structure and detect project type
├── `score-inject.sh` - Description: Emit a prompt-injection text block describing an agent's current rank/range
├── `score-update.sh` - Description: Update agent score by appending an entry to the lifecycle JSONL log.
├── `spec-check.py` - Subcommands: check-in, mark, waive, status, check-out, unlock
├── `stage-owned-hunks.py` - Stages ONLY this cycle's owned hunks within a single already-authorized file,
├── `step7-spec-update.py` - Step 8 (Spec-update dispatch) reference harness — task 20260524-205206 iter-2
├── `update-gitignore.sh` - update-gitignore.sh - Auto-update .gitignore with project-specific rules
├── `update-overnight-state.sh` - update-overnight-state.sh — Atomically update overnight state file
├── `write-bulk-commit-sentinel.py` - Invoked from commands/commit.md Step 5 (BULK=true) to authorize the
├── `write-codex-enforce.sh` - Writes codex-enforce.json into the dev-registry for the given session.
├── `write-commit-grant.py` - Invoked from `commands/commit.md` Step 5 (non-bulk mode) to author a
├── `write-e2e-enforce.sh` - Writes e2e-enforce.json into the dev-registry for the given session.
└── `write-qa-mode.sh` - Write or update qa_mode field in the QA sentinel file for a dev-registry session.
```
<!-- /AUTO:index-stats -->

---
*Auto-generated by doc-sync hook.*