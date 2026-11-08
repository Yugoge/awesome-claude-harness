---
description: Aggressive project cleanup - normalize docs structure, archive everything, delete one-time scripts/tests. Pass --codex to enable adversarial codex consultation on cleanliness-inspector and style-inspector; default is self-review only.
argument-hint: "[--codex]"
disable-model-invocation: true
---

# Clean Command Orchestrator

Aggressive project cleanup and normalization with orchestrated multi-agent workflow.

---

## Philosophy

Enforce strict organization standards through systematic inspection and selective cleanup.

---

## Orchestrator Rules -- DO NOT

**These rules are NON-NEGOTIABLE. Violating any of them is a critical workflow failure.**

The orchestrator (the LLM executing this command) MUST NOT:

1. **DO NOT use Edit, Write, or Bash tools to execute cleanup actions.** All file modifications during cleanup execution (Step 16) MUST be performed by the cleaner subagent, invoked via the Agent tool. The orchestrator coordinates; it does not execute.

2. **DO NOT subjectively filter or narrow scope when the user selects "Execute all".** "Execute all" means every finding from the combined report becomes an approved action. The orchestrator has zero discretion to classify findings as "not in scope", "minor", or "not worth doing". If the inspectors found it, it gets approved.

3. **DO NOT dismiss findings as "minor" or "not in scope" in aggressive mode.** When the user selects Option 1 (Execute all / aggressive), severity classification is irrelevant for approval purposes. All critical, major, AND minor findings are approved without exception.

4. **DO NOT build approval JSONs manually when Option 1 is selected.** The approvals must be mechanically generated from the combined report -- one approved_action per finding, no omissions, no editorial judgment.

5. **DO NOT execute any file modifications directly at any step.** The orchestrator's tools for cleanup execution are limited to the Agent tool (to invoke the cleaner subagent). This applies to Steps 11-12. Reading files and writing JSON coordination documents (docs/clean/) is permitted.

---

## Workflow Overview

This command dispatches five subagent types:

1. **rule-inspector** (Step 4): updates folder READMEs and INDEX.md files
2. **cleanliness-inspector** (Step 5): detects file organization issues
3. **style-inspector** (Steps 8 and 10, one per file group): audits development standards compliance
4. **prompt-inspector** (Step 10A): audits `agents/*.md` and `commands/*.md` verbosity
5. **cleaner** (Step 16): executes approved cleanup actions

Every dispatch is an Agent call with `run_in_background: false`. The request's JSON files live in `docs/clean/` (`scripts/orchestrator.sh`'s default `clean_output_dir`). `hooks/pretool-tool-policy.py` lets a subagent write the paths its dispatch declares (the obligation blocks of Steps 5, 8, 10A and 16 declare the reports their subagents write) and, beside them, only its policy row's directories: its own scratch directories, `docs/dev/overnight/`, and `docs/codex/` for the cleanliness-, style- and prompt-inspector. It refuses (exit 2) every other write of these five roles, under docs/ or anywhere else in the project, and reads no `/allow` grant; the cleaner's moves and `fix_style` edits are such writes (Step 16).

**Hook rejection (a process step, never a terminal):** a subagent whose operation a hook rejects never retries, disguises or circumvents it (no other tool, wrapper or script for the same write); it goes on with the rest of its work and reports the operation exactly as it ran and the hook's output. The orchestrator then asks the owner one AskUserQuestion inside the turn that names each refused action and its exact operation: that is the pause, and it releases no gate. The owner's answer decides each action refused by a hook that reads `/allow` grants. An operation `hooks/pretool-tool-policy.py` refused is not run again in this session (that hook reads no `/allow` grant and refuses the same write from the same role re-dispatched with the same template: paragraph above): the question states its outcome, the action withdrawn and recorded with the hook's output, and no later step of this command needs it, so no acceptance criterion is left for the owner to decide (Hook Discipline #4). One refused by a hook that reads `/allow` grants (`hooks/pretool-git-privilege-guard.py`: the cleaner's `git commit`) runs again only after the owner's `/allow` grant for it (for example `/allow git commit`; an AskUserQuestion answer writes no grant), when the orchestrator re-dispatches the same role with the same template and a fresh dispatched_at; or the owner leaves it undone. Neither the orchestrator nor a subagent retries an operation without that grant, each answer or withdrawal is that action's outcome in Steps 17 and 18, and the command continues to completion.

---

## Execution Steps

### Step 1: Initialize Workflow

**Parse `--codex`**: If `$ARGUMENTS` contains the literal token `--codex`, strip it from the arguments and set `codex_required = true`. Otherwise set `codex_required = false` (default). When `codex_required = true`, every cleanliness-inspector, style-inspector, and prompt-inspector dispatch prompt below MUST include the literal line `codex_required: true` so the subagent's opt-in codex consultation block activates. When `codex_required = false`, omit that line.

Load TodoList checklist: activate venv and run `~/.claude/scripts/todo/clean.py`.

Set up working directory: create `docs/clean/`, generate `REQUEST_ID="clean-$(date +%Y%m%d-%H%M%S)"` and `TIMESTAMP` in ISO-8601 format.

**Documentation Structure Rules**:

Root directory .md files:
- **ALLOWED**: README.md, ARCHITECTURE.md, CLAUDE.md (official Claude Code files, do not move)
- **MOVE TO docs/**: All other .md files in project root

docs/ subdirectory structure:
- `docs/guides/` - User guides, tutorials, how-to documents
- `docs/reference/` - Technical docs, API reference, registries
- `docs/planning/` - Planning docs, roadmaps, design proposals
- `docs/reports/` - Completion reports, summaries, QA reports
- `docs/archive/YYYY-MM/` - Historical docs (by last modified month)
- `docs/dev/` - Development workflow JSONs only (no .md files)
- `docs/clean/` - Clean workflow JSONs only (no .md files)
- `docs/INDEX.md` - Auto-generated index (created by cleaner agent)

### Step 2: Scan Project Structure

Detect project type and gather baseline info: run `~/.claude/scripts/scan-project.sh "$PROJECT_ROOT"` and extract `project_type`, `file_counts.total`, `.docs`, `.scripts`, `.tests` from the JSON output.

### Step 3: Build Inspection Context

Create comprehensive JSON context for inspectors:

```json
{
  "request_id": "clean-YYYYMMDD-HHMMSS",
  "timestamp": "ISO-8601",
  "orchestrator": {
    "requirement": "Inspect project for file organization issues and development standards violations",
    "analysis": {
      "project_root": "/absolute/path/to/project",
      "project_type": "Python|Node.js|Go|Generic",
      "constraints": [
        "preserve functional files",
        "safety first - never delete without confirmation",
        "archive docs rather than delete"
      ]
    }
  },
  "full_context": {
    "codebase_state": {
      "git_status": "output of git status",
      "current_branch": "branch name",
      "recent_commits": ["commit log"]
    },
    "directory_structure": "tree output or ls -R",
    "file_counts": {
      "total": 0,
      "docs": 0,
      "scripts": 0,
      "tests": 0
    }
  },
  "parameters": {
    "docs_directory": "docs/",
    "scripts_directory": "scripts/",
    "tests_directory": "tests/"
  }
}
```

Save to: `docs/clean/context-{REQUEST_ID}.json`

### Step 4: Rule Inspection and README Updates

**CRITICAL**: This step MUST execute BEFORE Step 5 on EVERY /clean run.

Run rule-inspector to update folder documentation with recent changes:

1. Discover all folders: `~/.claude/scripts/discover-folders.sh "$PROJECT_ROOT"`
2. Run freshness check: `~/.claude/scripts/check-readme-freshness.sh "$PROJECT_ROOT"` and save to `docs/clean/freshness-${REQUEST_ID}.json`
3. Build rule-inspector context JSON at `docs/clean/rule-context-${REQUEST_ID}.json` including request_id, timestamp, project_root, folders, freshness data, and parameters `freshness_check: true`, `update_stale_readmes: true`
4. Invoke: `~/.claude/scripts/orchestrator.sh rule-inspect "$RULE_CONTEXT"`, then dispatch the rule-inspector subagent with that context (Agent tool, `run_in_background: false`)
5. Verify `docs/clean/rule-context-${REQUEST_ID}.json` exists; abort with error if not
6. For each stale folder, verify the README was actually modified after the script start time; warn if not. The rule-inspector's `refused_operations` (its Step 6 edits of README.md and ARCHITECTURE.md, which `hooks/pretool-tool-policy.py` refuses) go to the owner by the hook-rejection rule (Workflow Overview), withdrawn and recorded with the hook's output

**What this step does**:
- Analyzes Git history for ALL folders (including root directory)
- Checks README freshness (compares README mtime vs folder content mtime)
- Updates stale READMEs (> 7 days old: full update, 3-7 days: incremental)
- **Special handling for root documentation files (README.md and ARCHITECTURE.md)**: Checks against structural changes, updates project-level overview (not folder rules)
- Creates README for folders that lack one
- Regenerates INDEX.md with current file inventory in the folders Step 5's clean-inspect checks
- Applies recency weighting (recent commits weighted 3x higher)

**Root documentation special processing**:
- Root `README.md` and `ARCHITECTURE.md` describe entire project structure, not folder-specific rules
- Freshness check compares against last structural change (new folders, archived folders, major commits)
- Update triggers when structural changes > 7 days old compared to documentation files
- README preserves user-written sections (Installation, Quick Start, Features), only regenerates Structure and Git Analysis
- ARCHITECTURE preserves user-written sections (Design Principles), only regenerates Directory Structure, Data Flow, and Git Analysis
- Different templates from subfolder READMEs (project overview, not organization rules)

**Verification**: Before proceeding to Step 5, you MUST confirm:
- ✅ Rule inspection completed (rule-context JSON exists)
- ✅ READMEs updated or confirmed fresh

Rule: rule-inspector runs on EVERY execution with freshness detection, never conditionally.

---

### Step 5: Invoke Cleanliness Inspector

Delegate to cleanliness-inspector subagent (Agent tool, `run_in_background: false`). The dispatch prompt MUST include:

```
Context file: docs/clean/context-{REQUEST_ID}.json
<obligation v="1">
{"task_id": null, "lane": null, "lane_set": null, "role": "cleanliness-inspector", "pipeline": "clean", "profile": "ad_hoc", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this dispatch, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>", "artifacts": [{"kind": "json", "path": "docs/clean/cleanliness-report-{REQUEST_ID}.json", "schema": "cleanliness-inspector-report.v1", "identity": {"request_id": "{REQUEST_ID}"}}]}
</obligation>
<If codex_required = true, include the literal next line; otherwise omit it>
codex_required: true
```

The obligation declares the report this dispatch owes: the inspector's stop checks it (present, valid JSON of its schema, this request's id) and returns a missing or invalid report to the inspector.

```bash
~/.claude/scripts/orchestrator.sh clean-inspect docs/clean/context-{REQUEST_ID}.json
```

Cleanliness inspector reads context, performs inspection, writes:
- `docs/clean/cleanliness-report-{REQUEST_ID}.json`

Expected output structure:

```json
{
  "request_id": "clean-YYYYMMDD-HHMMSS",
  "timestamp": "ISO-8601",
  "inspector": "cleanliness-inspector",
  "findings": {
    "misplaced_docs": [],
    "naming_violations": [],
    "archive_candidates": [],
    "dev_context_files": [],
    "temp_files": [],
    "duplicate_scripts": [],
    "duplicate_tests": [],
    "non_functional_files": []
  },
  "summary": {
    "total_issues": 0,
    "critical": 0,
    "major": 0,
    "minor": 0,
    "estimated_space_saved": "XX MB"
  }
}
```

### Step 6: Invoke Style Inspectors (Parallel Multi-Agent)

The style-inspector uses a **budget protocol** to avoid context overflow. Instead of looping sequentially, the orchestrator plans the inspection upfront and launches ALL inspector agents in one message, one per file group.

**Plan file**: `docs/clean/style-plan-{REQUEST_ID}.json`
**Partial reports**: `docs/clean/style-partial-{REQUEST_ID}-group-{GROUP_ID}.json`
**Final report**: `docs/clean/style-report-{REQUEST_ID}.json`

#### Step 7: Plan Style Inspection

Run the planner script to discover all auditable files and split them into groups: `~/.claude/scripts/plan-style-inspection.sh "$PROJECT_ROOT"`. Save to `docs/clean/style-plan-${REQUEST_ID}.json`. Extract `agent_count` and `total_files` from the output.

Log: "Style inspection planned: {AGENT_COUNT} agents for {TOTAL_FILES} files"

If AGENT_COUNT is 0, skip to Step 11 (no files to audit).

#### Step 8: Launch Parallel Style Inspectors

For EACH group in the plan JSON, launch a style-inspector agent using the **Agent tool** with `run_in_background: false`. All N calls MUST be made in a SINGLE message: N synchronous calls that run in parallel, the turn resuming when every one has returned.

Each agent's prompt MUST contain:

```
You are a style-inspector. Audit ONLY the files listed below against all 11 development standards.

Request ID: {REQUEST_ID}
Group ID: {GROUP_ID}
Project root: {PROJECT_ROOT}
Context file: docs/clean/context-{REQUEST_ID}.json
<obligation v="1">
{"task_id": null, "lane": null, "lane_set": null, "role": "style-inspector", "pipeline": "clean", "profile": "ad_hoc", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this dispatch, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>", "artifacts": [{"kind": "json", "path": "docs/clean/style-partial-{REQUEST_ID}-group-{GROUP_ID}.json", "schema": "style-inspector-report.v1", "identity": {"request_id": "{REQUEST_ID}"}}]}
</obligation>
<If codex_required = true, include the literal next line; otherwise omit it>
codex_required: true

Files to audit (audit EVERY file in this list, no others):
1. {file_path_1}
2. {file_path_2}
3. {file_path_3}
4. {file_path_4}
5. {file_path_5}

Write your partial report to: docs/clean/style-partial-{REQUEST_ID}-group-{GROUP_ID}.json
It is also your progress file and your final report: write neither anywhere else (Step 9 merges the partials into the style report).

The partial report MUST use this schema:
{
  "request_id": "{REQUEST_ID}",
  "timestamp": "ISO-8601",
  "inspector": "style-inspector",
  "group_id": {GROUP_ID},
  "files_audited": ["list of files you actually audited"],
  "violations": [
    {
      "standard": "standard-name",
      "severity": "critical",
      "location": "file:line",
      "finding": "description",
      "recommendation": "how to fix"
    }
  ],
  "summary": {"standards_checked": 11, "violations_found": 0, "critical": 0, "files_audited": 0, "files_total": 0},
  "codex_consult": {"invoked": false, "status": "not_requested", "findings": [], "feedback_summary": null, "feedback_incorporated": null},
  "status": "complete"
}

You MUST read each file fully before auditing it. Check all 11 standards against each file.
Your audit scope is exactly the files listed above. After auditing all of them, treat this as `STATUS: complete` for this invocation.
```

After all calls have returned, log: "Launched {AGENT_COUNT} style-inspector agents in parallel"

#### Step 9: Collect and Merge Results

After ALL agents complete, read each partial report file, the path each Step 8 obligation declares (one per plan group, `{GROUP_ID}` its `group_id`):

```
docs/clean/style-partial-{REQUEST_ID}-group-{GROUP_ID}.json
```

Merge all violations from every partial report into a single combined list. Merge all files_audited lists into a single deduplicated list. Write the final merged report to `docs/clean/style-report-{REQUEST_ID}.json`.

#### Step 10: Coverage Verification (MANDATORY GATE)

Read the plan file `docs/clean/style-plan-{REQUEST_ID}.json` and extract the `all_files` array. Compare it against the merged `files_audited` list from Step 9.

If ANY file from `all_files` is missing from the merged `files_audited`:

1. Log which files were missed and their count
2. Build a new group containing ONLY the missed files, with the next unused group ID
3. Launch a targeted style-inspector agent for the missed files (Agent tool, `run_in_background: false`; same prompt format as Step 8, including `codex_required: true` when `codex_required = true`)
4. After the targeted agent completes, merge its results into the final report
5. Repeat the coverage check, and items 1-4 for any file still missing

**BLOCK Step 11 until coverage verification passes** (all files in the plan appear in files_audited).

---

Expected final output structure:

```json
{
  "request_id": "clean-YYYYMMDD-HHMMSS",
  "timestamp": "ISO-8601",
  "inspector": "style-inspector",
  "violations": [
    {
      "standard": "standard-name",
      "severity": "critical",
      "location": "file:line",
      "finding": "description",
      "recommendation": "how to fix"
    }
  ],
  "summary": {
    "standards_checked": 11,
    "violations_found": 0,
    "critical": 0,
    "files_audited": 0,
    "files_total": 0,
    "rounds_completed": 0
  }
}
```

### Step 10A: Invoke Prompt Inspector (agents/ and commands/ verbosity)

The prompt-inspector is the only inspector that audits `agents/*.md` and `commands/*.md`; no other inspector in this workflow reaches those directories, so this step is MANDATORY on every /clean run. Delegate to the prompt-inspector subagent (Agent tool, `run_in_background: false`) with `docs/clean/context-{REQUEST_ID}.json` plus the literal lines `command_files: <every commands/*.md>` and `agent_files: <every agents/*.md>`, the block `<obligation v="1">{"task_id": null, "lane": null, "lane_set": null, "role": "prompt-inspector", "pipeline": "clean", "profile": "ad_hoc", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this dispatch, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>", "artifacts": [{"kind": "json", "path": "docs/clean/prompt-report-{REQUEST_ID}.json", "schema": "prompt-inspector-report.v1", "identity": {"request_id": "{REQUEST_ID}"}}]}</obligation>`, and `codex_required: true` only when `codex_required = true`. It writes `docs/clean/prompt-report-{REQUEST_ID}.json` (top-level `findings` array, one entry per file), the report the obligation declares: the inspector's stop checks it (present, valid JSON of its schema, this request's id) and returns a missing or invalid report to the inspector.

Coverage gate: every `commands/*.md` and `agents/*.md` file MUST appear in the report's audited-file list or be named in a finding; otherwise re-dispatch the prompt-inspector for the missed files, again until every file is covered, before Step 11.

### Step 11: Merge Inspection Reports

Combine the cleanliness, style and prompt reports using orchestrator: `~/.claude/scripts/orchestrator.sh clean-merge-reports docs/clean/context-{REQUEST_ID}.json`

Orchestrator reads `docs/clean/{cleanliness,style,prompt}-report-{REQUEST_ID}.json` and writes:
- `docs/clean/combined-report-{REQUEST_ID}.json`

### Step 12: Present Combined Report to User

Format and display findings:

```markdown
# Cleanup Analysis Report

**Project**: <project_name>
**Type**: <project_type>
**Generated**: <timestamp>

## File Organization Issues (Cleanliness Inspector)

### Critical Issues: X
- <critical findings>

### Major Issues: Y
- <major findings>

### Minor Issues: Z
- <minor findings>

## Development Standards Violations (Style Inspector)

### Critical Violations: X
- <critical violations>

### Major Violations: Y
- <major violations>

### Minor Violations: Z
- <minor violations>

## Prompt Verbosity Findings (Prompt Inspector — agents/ and commands/)

- <one line per finding: file, severity, verbose_lines, recommendation>

## Summary

- Total issues: X
- Estimated space to free: XX MB
- Files to move: Y
- Files to archive: Z
- Files to delete: W
- Style fixes: V

## Cleanup Options

1. Execute all recommended actions (aggressive)
2. Execute only file organization (conservative)
3. Execute only critical/major issues
4. Review and approve individually (interactive)
5. Cancel and generate report only
```

### Step 13: Collect User Approval

Ask the user to pick one of the Step 12 options with one AskUserQuestion inside the turn, then build the approval context from the answer:

**Option 1: Execute all (aggressive) -- MECHANICAL GENERATION**

When the user selects Option 1, the orchestrator MUST mechanically generate the approvals JSON by iterating ALL findings from the combined report. There is no manual curation, no editorial filtering, no severity-based exclusion.

Procedure:
1. Read `docs/clean/combined-report-{REQUEST_ID}.json`
2. Extract every finding from `findings` (cleanliness), `violations` (style), and `prompt_report.findings` (prompt verbosity; approved as action `fix_style` against the named `agents/` or `commands/` file)
3. For EACH finding, create one entry in `approved_actions` with `"approved": true`
4. Set `rejected_actions` to an empty array
5. Record `total_issues_in_report` (from combined report summary `total_issues`)
6. Record `total_approved_actions` (count of `approved_actions` array)
7. These two counts MUST be equal. If they differ, the generation has a bug -- do NOT proceed

```json
{
  "request_id": "clean-YYYYMMDD-HHMMSS",
  "timestamp": "ISO-8601",
  "mode": "execute_all",
  "user_approvals": {
    "total_issues_in_report": 92,
    "total_approved_actions": 92,
    "approved_actions": [
      {
        "action_id": "finding_1",
        "source_report": "cleanliness|style|prompt",
        "source_finding_index": 0,
        "action": "move|delete|archive|fix",
        "description": "copied from finding",
        "location": "file:line or file path",
        "approved": true
      }
    ],
    "rejected_actions": []
  }
}
```

**Option 2: File organization only** (approve cleanliness findings, skip style and prompt)

**Option 3: Critical/major only** (filter by severity)

**Option 4: Interactive** (one AskUserQuestion per action)

**Option 5: Report only** (skip to completion report)

For Options 2-4, the orchestrator may apply the stated filter (by report type, severity, or individual user decision). Only Option 1 requires mechanical all-inclusive generation.

Save to: `docs/clean/user-approvals-{REQUEST_ID}.json`

### Step 14: Verify Cleanup Completeness (Option 1 Only)

**This gate is MANDATORY when the user selected Option 1 (Execute all). Skip for Options 2-5.**

Before proceeding to Step 15, the orchestrator MUST verify that the approvals JSON is complete:

1. Read `total_issues` from `docs/clean/combined-report-{REQUEST_ID}.json` summary section
2. Read `total_approved_actions` from `docs/clean/user-approvals-{REQUEST_ID}.json`
3. Compare the two counts

**If counts match**: Log "Completeness gate PASSED: {total_approved_actions} approved actions match {total_issues} combined report findings" and proceed to Step 15.

**If counts do NOT match**: BLOCK execution immediately. Do NOT proceed to Step 15 or Step 16. Log the following error:

```
COMPLETENESS GATE FAILED
Mode: execute_all
Combined report total_issues: {N}
Approved actions count: {M}
Discrepancy: {N - M} findings missing from approvals
ACTION: Regenerate approvals JSON from combined report. Every finding must have a corresponding approved_action.
```

The orchestrator MUST regenerate the approvals JSON (return to Step 13 Option 1 procedure) and re-run this gate. Do NOT bypass the gate or proceed with mismatched counts.

---

### Step 15: Create Safety Checkpoint

Before execution, create a safety checkpoint on `refs/checkpoints/<branch>`
(NOT on HEAD — preserves git blame hygiene). The checkpoint-core library
handles the no-changes case (exit 0) and uses an isolated temp index so
your real staged area is untouched.

Run `bash ~/.claude/hooks/checkpoint.sh "Before /clean aggressive cleanup"`. Then read `refs/checkpoints/<branch>` and record the checkpoint commit via `~/.claude/scripts/orchestrator.sh record-checkpoint docs/clean/context-{REQUEST_ID}.json "$CHECKPOINT_COMMIT"`, which prints the `checkpoint_commit` Step 16 carries into the cleaner's context.

**Rollback**: The checkpoint lives on a detached ref, not as a HEAD
ancestor. To recover individual files:
`git checkout refs/checkpoints/$(git branch --show-current) -- <path>`
For a full-tree reset (destructive, prefer file-level):
`git reset --hard refs/checkpoints/$(git branch --show-current)`

### Step 16: Invoke Cleaner with Approvals (DELEGATION ONLY)

**The orchestrator MUST delegate ALL cleanup execution to the cleaner subagent via the Agent tool. The orchestrator does NOT execute any file modifications itself.**

**DO NOT -- the following are FORBIDDEN during Step 16:**
- **DO NOT use the Edit tool** to modify any project files
- **DO NOT use the Write tool** to create or overwrite any project files
- **DO NOT use the Bash tool** to run commands that modify files (mv, cp, rm, sed, etc.)
- **DO NOT use any tool other than Agent** for cleanup execution
- **The ONLY tool permitted for cleanup execution is the Agent tool** (to invoke the cleaner subagent)

The orchestrator may use Bash to prepare the context JSON (merging approvals), but MUST NOT use Bash/Edit/Write to make any changes to project files.

Prepare context for the cleaner subagent:

```bash
jq -s --arg commit "<checkpoint_commit from Step 15>" \
  '.[0] * {user_approvals: .[1].user_approvals} * {orchestrator: {analysis: {safety_checkpoint_created: true, checkpoint_commit: $commit}}}' \
  docs/clean/context-{REQUEST_ID}.json \
  docs/clean/user-approvals-{REQUEST_ID}.json \
  > docs/clean/context-with-approvals-{REQUEST_ID}.json
```

Invoke the cleaner subagent using the Agent tool (`run_in_background: false`):

The orchestrator MUST use the Agent tool with the cleaner subagent prompt. The cleaner subagent reads `docs/clean/context-with-approvals-{REQUEST_ID}.json`, executes ALL approved actions, and writes its execution report.

```
Agent tool invocation:
  run_in_background: false
  prompt: "You are the cleaner subagent.

Read these report files directly from the filesystem:
- Combined report: docs/clean/combined-report-{REQUEST_ID}.json
- Style report: docs/clean/style-report-{REQUEST_ID}.json
- Cleanliness report: docs/clean/cleanliness-report-{REQUEST_ID}.json
- User approvals: docs/clean/user-approvals-{REQUEST_ID}.json

The merged context with approvals is at: docs/clean/context-with-approvals-{REQUEST_ID}.json
<obligation v="1">
{"task_id": null, "lane": null, "lane_set": null, "role": "cleaner", "pipeline": "clean", "profile": "ad_hoc", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this dispatch, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>", "artifacts": [{"kind": "markdown", "path": "docs/clean/cleanup-execution-{REQUEST_ID}.json", "identity_anchor": "{REQUEST_ID}", "terminal_line_regex": "^}$"}]}
</obligation>

Execute ALL approved_actions. Write results to docs/clean/cleanup-execution-{REQUEST_ID}.json."
```

The obligation declares the execution report (kind `markdown`: no registered schema covers it, so the cleaner's stop checks that it exists, names this request's id and ends with a line holding only its closing `}`, and returns a missing or cut-off report to the cleaner). It declares none of the project files the approved actions move or edit: a declaration would hold each of them for this cleaner for the rest of the session, and a path no command template's shape covers (a script's `fix_style` edit) is not held by a declaration at all. So `hooks/pretool-tool-policy.py` refuses (exit 2) the destination of every move, archive and rename (`mv`) and every `fix_style` edit (Edit) the cleaner makes; it judges no write target in the cleaner's `rm`, `git add` and helper-script calls (delete, `update_gitignore`, `generate_index`, `merge_test_folders`, `cleanup_tests`). `hooks/pretool-git-privilege-guard.py` refuses (exit 2) the cleaner's `git commit` unless the owner's `/allow` grants that command.

The orchestrator MUST NOT supplement, assist, or "help" the cleaner by making additional edits. A refusal is a hook rejection, not a failure: the cleaner lists each refused operation in `actions_refused` and runs the rest. After the cleaner returns, the orchestrator reads the execution report; when `actions_refused` is not empty it follows the hook-rejection rule (Workflow Overview): one AskUserQuestion inside the turn naming each refused action and its exact operation, its options the owner's decisions that rule names. For the refused `git commit`, the re-dispatched cleaner commits and writes the push-gate token; left undone, the changes stay staged and uncommitted. An action that fails for another reason (its source is gone) stays in `actions_failed` with that reason; the orchestrator does not retry it directly.

Cleaner reads approvals, executes actions, writes:
- `docs/clean/cleanup-execution-{REQUEST_ID}.json`

Expected output structure:

```json
{
  "request_id": "clean-YYYYMMDD-HHMMSS",
  "timestamp": "ISO-8601",
  "cleaner": {
    "status": "completed|partial",
    "actions_completed": [],
    "actions_failed": [],
    "actions_skipped": [],
    "actions_refused": [],
    "summary": {
      "total_actions": 10,
      "successful": 8,
      "failed": 0,
      "skipped": 2,
      "refused": 0,
      "files_moved": 3,
      "files_archived": 2,
      "files_deleted": 3,
      "space_freed": "15 MB"
    },
    "git_status": {
      "checkpoint_commit": "abc123",
      "cleanup_commit": "def456",
      "files_staged": 8,
      "ready_for_review": true
    }
  }
}
```

### Step 17: Verify Cleanup Results

Review git changes: check `git status`; when the execution report names a `cleanup_commit`, also `git diff --stat HEAD~1`. The summary states what happened, from the execution report, the owner's answers (Step 16) and these calls: a cleanup commit only when the report names one, else none.

Present verification summary:

```markdown
# Cleanup Execution Results

**Status**: <completed|partial>
**Actions**: X successful, Y failed, Z skipped, R refused by a hook (each with the owner's answer, or withdrawn)

## Changes Made

- Moved X files to correct locations
- Archived Y old documents
- Deleted Z temp files
- Fixed W style violations
- Updated .gitignore

## Git Status

- Checkpoint commit: <hash>
- Cleanup commit: <hash, or none: no change staged, or the commit refused (Step 16)>
- Files changed: X
- Ready for review: <yes with a cleanup commit, else no>

## Next Steps

1. Review changes: `git diff HEAD~1` with a cleanup commit, else `git status`
2. If satisfied: with a cleanup commit, the changes are committed (to publish to remote: run `/push`); without one, nothing was committed, and `git status` shows what the cleaner staged
3. If not satisfied: `git reset --hard <checkpoint_commit>`
4. See detailed report: docs/clean/completion-{REQUEST_ID}.md
```

### Step 18: Generate Completion Report

Create comprehensive completion report:

Save to: `docs/clean/completion-{REQUEST_ID}.md`

```markdown
# Cleanup Completion Report

**Request ID**: clean-YYYYMMDD-HHMMSS
**Project**: <project_path>
**Type**: <project_type>
**Executed**: <timestamp>
**Status**: <completed|partial>

---

## Inspection Summary

### Cleanliness Issues Found
- Total: X
- Critical: Y
- Major: Z
- Minor: W

### Style Violations Found
- Total: X
- Critical: Y
- Major: Z
- Minor: W

---

## Actions Executed

### File Organization (X actions)
- Moved Y misplaced docs to docs/
- Archived Z old documents to docs/archive/
- Deleted W temp files
- Renamed V files to kebab-case

### Style Fixes (X actions)
- Fixed Y hardcoded URLs
- Fixed Z python3 calls to use venv
- Fixed W naming violations

---

## Results

### Successful (X actions)
<list of successful actions>

### Failed (Y actions)
<list of failed actions with reasons>

### Skipped (Z actions)
<list of skipped actions with reasons>

### Refused by a hook (R actions)
<list of refused actions: exact operation, the hook's output, the owner's answer or withdrawn>

---

## Summary Statistics

- Space freed: XX MB
- Files moved: Y
- Files archived: Z
- Files deleted: W
- Style fixes: V
- Git commits: <the checkpoint, plus the cleanup commit when the execution report names one>

---

## Git Information

- Checkpoint commit: <hash>
- Cleanup commit: <hash>
- Branch: <branch>
- Files changed: X
- Rollback command: `git reset --hard <checkpoint_commit>`

---

## Related Files

- Context: docs/clean/context-{REQUEST_ID}.json
- Cleanliness report: docs/clean/cleanliness-report-{REQUEST_ID}.json
- Style report: docs/clean/style-report-{REQUEST_ID}.json
- Combined report: docs/clean/combined-report-{REQUEST_ID}.json
- User approvals: docs/clean/user-approvals-{REQUEST_ID}.json
- Execution report: docs/clean/cleanup-execution-{REQUEST_ID}.json

---

**Root Cause**: Project files evolved organically without consistent organization standards. Manual cleanup was error-prone and time-consuming.

**Solution**: Implemented orchestrated multi-agent cleanup workflow with automated detection, user approval, and safe execution.

**Next Steps**: Run /clean periodically to maintain organization standards.
```

---

## Safety Features

### Git Checkpoint
- Automatic commit before cleanup
- Easy rollback with `git reset --hard <checkpoint>`

### User Approval
- No automatic deletion without confirmation
- Interactive approval for all actions
- Clear categorization by severity

### Reference Detection
- Uses `check-file-references.sh` for safety
- Preserves files with functional references
- Archives instead of deleting when uncertain

### Incremental Execution
- Stages after each category, then one cleanup commit (Step 16: refused unless the owner's `/allow` grants it)
- Continues past a failed or refused action; a refused one goes to the owner (hook-rejection rule)
- Reports all results

---

## Quality Standards

### Agent Communication
- All via JSON in docs/clean/
- Structured schemas enforced
- Clear request_id tracking

### Documentation
- Comprehensive reports generated
- Git rationale included
- Easy to audit and review

### Orchestration Pattern
- Follows /dev workflow model
- Specialized subagents
- Clear separation of concerns

---

## Helper Scripts Used

- `~/.claude/scripts/check-file-references.sh` - Reference detection
- `~/.claude/scripts/normalize-doc-names.sh` - Naming validation
- `~/.claude/scripts/update-gitignore.sh` - Gitignore updates
- `~/.claude/scripts/orchestrator.sh` - Agent coordination
- `~/.claude/scripts/todo/clean.py` - Workflow checklist

---

## Usage

Execute in any project directory:

```bash
cd /path/to/project
# In Claude Code, invoke: /clean
```

The orchestrator will guide you through all steps interactively.

---

**Remember**: This is an aggressive cleanup command with safety features. First-time users should select "Report only" mode to review findings before executing cleanup actions.

**Graphify**: Graphify knowledge graph integration is **disabled** for /clean. No graphify-query.py or graphify-enrich.py calls are made during clean cycles.
