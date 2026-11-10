# scripts

Organization and usage documentation for `scripts/`.

<!-- AUTO:readme-stats -->
## Overview
- **Total files**: 109
- **Subdirectories**: 7
- **Naming convention**: kebab

## Files
- `aggregate-dev-report.py` - Scans docs/dev/ for per-worker shard dev-reports matching a given task-id,
- `aggregate-permissions.py` - Usage: aggregate-permissions.py <qa-glob-or-dir> [pipelines.json]
- `analyze-git-edge-cases.sh` - Description: Analyze git history for edge cases from bug fix commits
- `apply-permissions.sh` - apply-permissions.sh — merge aggregated permissions JSON list into settings.json
- `blast-radius-tool.py` - Two phases:
- `bootstrap` - bootstrap file
- `break-overnight-lock.py` - The time-lock is released by the human-typed /stop record itself
- `build-pipelines-from-triage.py` - Consumes PM triage schema (issues[] keyed by triage_index + pipeline_order[] +
- `canary-verify.sh` - Description: Cache-safe canary that behaviorally verifies the four core PreToolUse hooks.
- `capability-doctor-strict.py` - Two properties this file exists to guarantee:
- `capability-handshake.py` - Proves (or refuses to claim) that this harness's hook-based security boundary is
- `capability-status-line.sh` - Description: statusLine command that renders the persistent host-capability marker.
- `capture-hero-run.py` - Description: Builds a hermetic fixture, installs one narrowly-scoped single-use grant,
- `check-enforcement-evidence.py` - Three subcommands, one consumer each:
- `check-file-references.sh` - File reference detection script - used by /clean command
- `check-late-repair-provenance.py` - Takes ONLY ``--task-id`` and ``--project-dir`` (never a caller-supplied file
- `check-overnight-reports.sh` - STUB: each specialist's dispatch obligation declares its report and schema, and G2
- `check-public-core.sh` - Description: Public/private boundary gate, the one privacy engine. Recomputes the top-level
- `check-readme-freshness.sh` - Check README.md freshness for all major folders
- `checkpoint-prune.sh` - checkpoint-prune.sh — trim refs/checkpoints/* to the most recent N commits
- `cleanup-tests-folder.sh` - Description: Remove validators that don't match git edge cases, preserving reports/
- `close-report-append.py` - Description: Deterministic read-append-reread-verify helper for the
- `close-route-select.py` - COMPATIBILITY CODE (live landing, D15/D25), kept like the old permission spellings of D14:
- `commit.sh` - Description: Kept, run by no command since P2 (D15: no feature is retired).
- `create-overnight-state.sh` - create-overnight-state.sh — Create overnight state file (v7 schema)
- `create-worktree.sh` - Create a git worktree from local HEAD (not origin/main).
- `derive-default-branch.sh` - Description: Resolve the repository's default branch name dynamically (handles main/master/any other).
- `detect-dead-functions.sh` - Shell script
- `detect-duplicate-content.sh` - Shell script
- `detect-merge-conflicts.sh` - Shell script
- `detect-orphan-agents.sh` - Description: Detect agents not referenced by any command
- `detect-orphan-commands.sh` - Description: Detect orphan commands (one-time patterns, no todo script, unused)
- `detect-orphan-scripts.sh` - Description: Detect scripts not referenced by any command/agent/other script
- `dev-lifecycle.py` - Derives, per on-disk task-id, a state (docs/dev/ticket-20260808-035658-lanel.md):
- `discover-folders.sh` - Description: Dynamically discover project folders excluding system directories
- `doctor` - doctor file
- `execute-push.py` - Eliminates the timing window that exists when validate + push are && -chained
- `generate-folder-index.sh` - Description: Generate INDEX.md for folder (inventory of contents)
- `generate-folder-readme.sh` - Description: Generate README.md for folder (purpose and organization rules)
- `generate-hero-status.py` - Description: One source of truth emits SIX marker-delimited canonical regions in two documents and
- `graphify-enrich.py` - graphify-enrich.py — pre-DEV focused subgraph extractor (runs between Step 7 and Step 8)
- `graphify-maintain.py` - graphify-maintain.py — Global Graphify cache lifecycle manager (REAL CLI)
- `graphify-query.py` - graphify-query.py — deterministic pre-BA graph hydrator (runs between Step 1 and Step 2)
- `graphify_lib.py` - graphify_lib.py — shared library for Graphify knowledge-graph integration
- `install-checkpoint-refspec.sh` - install-checkpoint-refspec.sh — idempotently add refs/checkpoints/* to
- `install-git-keystone.sh` - install-git-keystone.sh — wire the git-native reference-transaction keystone
- `iterate-failed-pipelines.py` - COMPATIBILITY CODE (live landing, D15/D25), kept like the old permission spellings of D14:
- `late-repair-controller.py` - Owns the run-record lifecycle for the deliberately-invoked ``/close
- `lint-spec-id-centralization.py` - markdown from re-deriving a spec-id / views_dir / split_marker / cp_dir from a
- `measure-hero-fold.py` - Description: Renders the document that holds the hero, docs/status.md, LOCALLY from the
- `migrate-test-to-tests.sh` - Description: Merge test/ folder into tests/ preserving all content (idempotent)
- `mint-git-blessed-token.sh` - mint-git-blessed-token.sh — issuer of the keystone blessed token (M12).
- `normalize-doc-names.sh` - normalize-doc-names.sh - Detect and report non-compliant documentation file names
- `orchestrator.sh` - Description: Agent orchestration coordinator for development and cleanup workflows
- `overnight-git-env.sh` - overnight-git-env.sh — prepare the overnight actor's git PATH + env (M11/AC9).
- `overnight-git-selftest.sh` - overnight-git-selftest.sh — launch git-version + symref self-test (M8, M16).
- `overnight-init.sh` - overnight-init.sh — perform the ENTIRE /dev-overnight Step 1 initialization in
- `overnight-inplace-env.sh` - overnight-inplace-env.sh — export the overnight ACTOR MARKER, and nothing else.
- `overnight-status.sh` - overnight-status.sh — Zero-LLM overnight session status query
- `paseo-daemon-ledger.py` - Deterministic CLI realizing blueprint F6/F8/F10/F11/F14 local-persistence
- `paseo-daemon-timers.py` - four paseo-daemon timer schedules (tick, ctrl-core-reinject, watchdog,
- `paseo-usage-read.mjs` - mjs file
- `plan-style-inspection.sh` - Description: Discover auditable files and split into groups for parallel style inspection
- `precommitted-recovery.sh` - Description: Recovery path helpers for nothing_to_commit_precommitted detection.
- `prune-orphaned-workflow-bookmarks.sh` - scripts/prune-orphaned-workflow-bookmarks.sh
- `qa-manifest-guard.py` - Dual-mode tool per BA spec docs/dev/ticket-20260529-081014.md M4:
- `qa-report-stale-iter-lint.py` - lacks an explicit resolution marker
- `rating-view.py` - Behind /rating: print the score log's per-agent view of the current project. Reads only; exit 0 even for a log it cannot read.
- `readme_facts.py` - Description: One module, one function per fact, one source per function. No number is typed here:
- `refine-context.sh` - STUB: the QA-fail loop re-dispatches dev with the QA report path; no context is merged any more.
- `repair-venv.sh` - repair-venv.sh — durably restore a Python venv when its bin/python3 symlink target is missing.
- `resolve-close-report.sh` - Resolve the close-report path for a given TASK_ID using subproject path-walk.
- `resolve-commit-repos.py` - The normal ``/commit`` workflow uses this helper before it writes any commit
- `resolve-dev-artifact-chain.py` - The resolver never creates, refreshes, or rewrites artifacts.  It validates the
- `resolve-dev-report.py` - Usage:
- `resolve-spec-artifacts.py` - spec-id resolver shared by /spec finalize and every /dev* consumer)
- `restart-subagents.py` - CLI bridge for the human-only /restart recovery workflow.
- `runcode-watchdog.py` - Watchdog process for browser_run_code timeout enforcement
- `scan-project.sh` - Description: Scan project structure and detect project type
- `seal-attribution-journal.py` - The repo tree (journals under state/attribution-journal/ AND the git object
- `session-index.py` - Subcommands (all take --git-root):
- `session-resources.py` - Provider-neutral CLI for the LANE-B session resource broker.
- `size-ratchet.py` - Usage:
- `spec-check.py` - Subcommands: check-in, register, checkpoints, mark, waive, status, check-out, unlock
- `spec-write.py` - Every write of a spec file runs through this script: /spec's own writes (the
- `stage-owned-hunks.py` - Stages ONLY this cycle's owned hunks within a single already-authorized file,
- `step7-spec-update.py` - Step 8 (Spec-update dispatch) reference harness — task 20260524-205206 iter-2
- `test` - test file
- `update-gitignore.sh` - update-gitignore.sh - Auto-update .gitignore with project-specific rules
- `verify-attribution-chain.py` - Folds each file's events across ALL session journals into a hash chain and
- `verify-claims.sh` - Description: Self-verifying headline-claims gate. Runs ALL THREE hero-provenance audits in
- `verify-hero-provenance.py` - Description: Re-runs the demo, normalizes both outputs and byte-diffs them; verifies raw
- `verify-release-manifest.sh` - Description: Verify a PUBLISHED release artifact end-to-end, WITHOUT rebuilding it.
- `write-bulk-commit-sentinel.py` - Invoked from commands/commit.md Step 5 (BULK=true) to authorize the
- `write-commit-grant.py` - Invoked from `commands/commit.md` Step 5 (non-bulk mode) to author a
- `write-e2e-enforce.sh` - STUB: the E2E gate (hooks/subagentstop-e2e-enforce.py) has no flag; it judges
- `write-enforce-flag.sh` - Write one or more enforcement-flag sentinels into a dev-registry session dir.
- `write-git-residual-override.py` - Answers the "could not be statically classified" refusal emitted by
- `write-push-gate-token.py` - Run after its own commit by both of the token's callers: changelog-analyst under
- `write-qa-mode.sh` - STUB: P1b E7 replaced the qa_mode switch with the record: each QA dispatch's

## Subdirectories
- `install/`
- `lib/`
- `modern-git-slot/`
- `overnight-git/`
- `spec-verify/`
- `steps/`
- `todo/`
<!-- /AUTO:readme-stats -->

---

*Auto-generated by doc-sync hook. Manual edits outside AUTO markers are preserved.*
