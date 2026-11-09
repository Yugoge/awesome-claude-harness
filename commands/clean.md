---
description: Aggressive project cleanup - normalize docs structure, discard tracked byproducts (old docs, one-time scripts and tests) with a recoverable git rm. Pass --codex to enable adversarial codex consultation on cleanliness-inspector and style-inspector; default is self-review only.
argument-hint: "[--codex]"
disable-model-invocation: true
---

# Clean Command Orchestrator

## Orchestrator Rules -- DO NOT

**These rules are NON-NEGOTIABLE.** The orchestrator (the LLM executing this command) MUST NOT:

1. **Change a project file at any step.** Every change (Step 16) is made by the cleaner subagent, invoked through the Agent tool, and the orchestrator does not supplement it with edits of its own. It reads files, writes the JSON coordination documents and the completion report in `docs/clean/`, and runs the Bash calls this command names.
2. **Narrow the findings when the owner selects "Execute all".** Every finding of the combined report, critical, major and minor alike, becomes an approved action; the orchestrator has no discretion to call one minor or not in scope, and does not build the approvals JSON by hand (Step 13 generates it mechanically, one approved action per finding).

## Workflow Overview

Five subagent types: **rule-inspector** (Step 4: folder READMEs and INDEX.md files), **cleanliness-inspector** (Step 5: file organization), **style-inspector** (Steps 8 and 10, one per file group: development standards), **prompt-inspector** (Step 10A: verbosity of `agents/*.md` and `commands/*.md`), **cleaner** (Step 16: the approved actions).

Every dispatch is an Agent call with `run_in_background: false`. The request's JSON files live in `docs/clean/` (`scripts/orchestrator.sh`'s default `clean_output_dir`). A dispatch's obligation block (its `dispatched_at` is the UTC time, `date -u +%Y-%m-%dT%H:%M:%SZ`, captured immediately before that dispatch) declares the report its subagent owes; the subagent's stop checks it (present, valid for its schema, this request's id) and returns a missing or invalid one to the subagent. `hooks/pretool-tool-policy.py` lets a subagent write only the paths its dispatch declares and refuses (exit 2) every other project write of these five roles, so the cleaner's moves and `fix_style` edits and the rule-inspector's README edits come back as refused operations (Steps 4 and 16). Graphify is disabled for /clean: no `graphify-query.py` or `graphify-enrich.py` call is made.

**Hook rejection (a process step, never a terminal):** a subagent whose operation a hook rejects never retries, disguises or circumvents it; it goes on with the rest of its work and reports the operation as it ran and the hook's output. The orchestrator then asks the owner one AskUserQuestion inside the turn that names each refused action and its exact operation: that is the pause, and it releases no gate. The owner's answer decides each action refused by a hook that reads `/allow` grants. An operation `hooks/pretool-tool-policy.py` refused is not run again in this session (that hook reads no `/allow` grant and refuses the same write from the same role re-dispatched with the same template): the question states its outcome, the action withdrawn and recorded with the hook's output, and offers "Withdraw it (Recommended)" or "Record it as a follow-up for a /dev cycle" (still withdrawn in this run; a /dev cycle's dev role, whose row in `policies/tool-policy.v1.json` allows `*`, may write the path), in a question of its own beside a grant decision; no acceptance criterion is left for the owner to decide (Hook Discipline #4). One refused by a hook that reads `/allow` grants (`hooks/pretool-git-privilege-guard.py`: the cleaner's `git commit`) runs again only after the owner's `/allow` grant for it (for example `/allow git commit`; an AskUserQuestion answer writes no grant), when the orchestrator re-dispatches the same role with the same template and a fresh dispatched_at; or the owner leaves it undone. The command continues to completion, and each answer or withdrawal is that action's outcome in Steps 17 and 18.

## Execution Steps

### Step 1: Initialize Workflow

**Parse `--codex`**: if `$ARGUMENTS` contains the literal token `--codex`, strip it from the arguments and set `codex_required = true`; otherwise `codex_required = false` (default). When true, every cleanliness-inspector, style-inspector and prompt-inspector dispatch prompt below carries the literal line `codex_required: true` (it activates the inspector's codex consultation block); when false it carries none.

Load TodoList checklist: run `python3 "<HARNESS_ROOT>/scripts/todo/clean.py"`.

Set up working directory: create `docs/clean/`, generate `REQUEST_ID="clean-$(date +%Y%m%d-%H%M%S)"` and `TIMESTAMP` in ISO-8601 format. `{REQUEST_ID}` below is that value.

**Documentation Structure Rules**:

- Root directory .md files: ALLOWED: README.md, ARCHITECTURE.md, CLAUDE.md (official Claude Code files, do not move); every other root .md file moves to `docs/`.
- `docs/guides/` user guides, tutorials, how-tos; `docs/reference/` technical docs, API reference, registries; `docs/planning/` planning docs, roadmaps, design proposals; `docs/reports/` completion reports, summaries, QA reports
- Historical docs: discarded with git rm; git history is the archive
- `docs/dev/` - development workflow JSONs only (no .md files)
- `docs/clean/` - this command's workflow files: the JSON documents of Steps 3-16 and Step 18's `completion-<id>.md`
- `docs/INDEX.md` - auto-generated index (created by the cleaner agent)

### Step 2: Scan Project Structure

Detect project type and gather baseline info: run `bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/scan-project.sh" "$PROJECT_ROOT"` and extract `project_type`, `file_counts.total`, `.docs`, `.scripts`, `.tests` from the JSON output.

### Step 3: Build Inspection Context

Create the JSON context for the inspectors:

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
        "discard tracked byproducts with git rm (no -f); git history is the archive"
      ]
    }
  },
  "full_context": {
    "codebase_state": {"git_status": "output of git status", "current_branch": "branch name", "recent_commits": ["commit log"]},
    "directory_structure": "tree output or ls -R",
    "file_counts": {"total": 0, "docs": 0, "scripts": 0, "tests": 0}
  },
  "parameters": {"docs_directory": "docs/", "scripts_directory": "scripts/", "tests_directory": "tests/"}
}
```

Save to: `docs/clean/context-{REQUEST_ID}.json`

### Step 4: Rule Inspection and README Updates

Run rule-inspector to update the folder READMEs and INDEX.md files on EVERY /clean run, with freshness detection, never conditionally, and before Step 5:

1. Discover all folders: `bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/discover-folders.sh" "$PROJECT_ROOT"`
2. Run freshness check: `bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/check-readme-freshness.sh" "$PROJECT_ROOT"` and save to `docs/clean/freshness-{REQUEST_ID}.json`
3. Build rule-inspector context JSON at `docs/clean/rule-context-{REQUEST_ID}.json` including request_id, timestamp, project_root, folders, freshness data, and parameters `freshness_check: true`, `update_stale_readmes: true`
4. Invoke: `bash "<HARNESS_ROOT>/scripts/orchestrator.sh" rule-inspect docs/clean/rule-context-{REQUEST_ID}.json`, then dispatch the rule-inspector subagent with that context (Agent tool, `run_in_background: false`)
5. Verify `docs/clean/rule-context-{REQUEST_ID}.json` exists; abort with error if not
6. For each stale folder, verify the README was actually modified after the script start time; warn if not. The rule-inspector's `refused_operations` (its Step 6 edits of README.md and ARCHITECTURE.md, which `hooks/pretool-tool-policy.py` refuses) go to the owner by the hook-rejection rule (Workflow Overview), withdrawn and recorded with the hook's output

### Step 5: Invoke Cleanliness Inspector

```bash
bash "<HARNESS_ROOT>/scripts/orchestrator.sh" clean-inspect docs/clean/context-{REQUEST_ID}.json
```

Then delegate to the cleanliness-inspector subagent (Agent tool, `run_in_background: false`). The dispatch prompt includes:

```
Context file: docs/clean/context-{REQUEST_ID}.json
<obligation v="1">
{"task_id": null, "lane": null, "lane_set": null, "role": "cleanliness-inspector", "pipeline": "clean", "profile": "ad_hoc", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this dispatch>", "artifacts": [{"kind": "json", "path": "docs/clean/cleanliness-report-{REQUEST_ID}.json", "schema": "cleanliness-inspector-report.v1", "identity": {"request_id": "{REQUEST_ID}"}}]}
</obligation>
<If codex_required = true, include the literal next line; otherwise omit it>
codex_required: true
```

It reads the context, inspects, and writes `docs/clean/cleanliness-report-{REQUEST_ID}.json`, in the shape of the Output Format of `agents/cleanliness-inspector.md`.

### Step 6: Invoke Style Inspectors (Parallel Multi-Agent)

Steps 7-10 plan the inspection, launch every style-inspector in one message (one per file group; the budget protocol of `agents/style-inspector.md`), merge the partial reports and verify coverage.

#### Step 7: Plan Style Inspection

Run the planner script to discover all auditable files and split them into groups: `bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/plan-style-inspection.sh" "$PROJECT_ROOT"`. Save to `docs/clean/style-plan-{REQUEST_ID}.json`. Extract `agent_count` and `total_files` from the output.

Log: "Style inspection planned: {AGENT_COUNT} agents for {TOTAL_FILES} files"

If AGENT_COUNT is 0, skip to Step 11 (no files to audit).

#### Step 8: Launch Parallel Style Inspectors

For EACH group in the plan JSON, launch a style-inspector agent (Agent tool, `run_in_background: false`). All N calls are made in a SINGLE message: N synchronous calls that run in parallel, the turn resuming when every one has returned.

Each agent's prompt contains:

```
You are a style-inspector. Audit ONLY the files listed below against all 11 development standards.

Request ID: {REQUEST_ID}
Group ID: {GROUP_ID}
Project root: {PROJECT_ROOT}
Context file: docs/clean/context-{REQUEST_ID}.json
<obligation v="1">
{"task_id": null, "lane": null, "lane_set": null, "role": "style-inspector", "pipeline": "clean", "profile": "ad_hoc", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this dispatch>", "artifacts": [{"kind": "json", "path": "docs/clean/style-partial-{REQUEST_ID}-group-{GROUP_ID}.json", "schema": "style-inspector-report.v1", "identity": {"request_id": "{REQUEST_ID}"}}]}
</obligation>
<If codex_required = true, include the literal next line; otherwise omit it>
codex_required: true

Files to audit (one numbered line per file; audit EVERY file in this list, no others):
1. {file_path_1}
2. {file_path_2}

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

Read each file fully before auditing it and check all 11 standards against it. Your audit scope is exactly the files listed above; after auditing all of them, treat this as `STATUS: complete` for this invocation.
```

After all calls have returned, log: "Launched {AGENT_COUNT} style-inspector agents in parallel"

#### Step 9: Collect and Merge Results

After ALL agents complete, read each partial report (the path each Step 8 obligation declares, `docs/clean/style-partial-{REQUEST_ID}-group-{GROUP_ID}.json`, one per plan group). Merge all violations into a single combined list and all `files_audited` lists into a single deduplicated list. Write the final merged report to `docs/clean/style-report-{REQUEST_ID}.json`, in the shape of the final report in the Output Format of `agents/style-inspector.md`.

#### Step 10: Coverage Verification (MANDATORY GATE)

Read `all_files` from the plan file `docs/clean/style-plan-{REQUEST_ID}.json` and compare it with the merged `files_audited` list from Step 9. For every file missing: log the missed files and their count, launch one more style-inspector for ONLY the missed files (next unused group ID; Step 8's prompt, Agent tool, `run_in_background: false`), merge its results into the final report, and check again until none is missing. Step 11 does not start before coverage passes.

### Step 10A: Invoke Prompt Inspector (agents/ and commands/ verbosity)

The prompt-inspector is the only inspector that audits `agents/*.md` and `commands/*.md`, so this step runs on every /clean run. Delegate to the prompt-inspector subagent (Agent tool, `run_in_background: false`) with `docs/clean/context-{REQUEST_ID}.json` plus the literal lines `command_files: <every commands/*.md>` and `agent_files: <every agents/*.md>`, the block `<obligation v="1">{"task_id": null, "lane": null, "lane_set": null, "role": "prompt-inspector", "pipeline": "clean", "profile": "ad_hoc", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this dispatch>", "artifacts": [{"kind": "json", "path": "docs/clean/prompt-report-{REQUEST_ID}.json", "schema": "prompt-inspector-report.v1", "identity": {"request_id": "{REQUEST_ID}"}}]}</obligation>`, and `codex_required: true` only when `codex_required = true`. It writes `docs/clean/prompt-report-{REQUEST_ID}.json` (top-level `findings` array, one entry per file).

Coverage gate: every `commands/*.md` and `agents/*.md` file appears in the report's audited-file list or is named in a finding; otherwise re-dispatch the prompt-inspector for the missed files, until every file is covered, before Step 11.

### Step 11: Merge Inspection Reports

Combine the cleanliness, style and prompt reports: `bash "<HARNESS_ROOT>/scripts/orchestrator.sh" clean-merge-reports docs/clean/context-{REQUEST_ID}.json`. It reads `docs/clean/{cleanliness,style,prompt}-report-{REQUEST_ID}.json` and writes `docs/clean/combined-report-{REQUEST_ID}.json`.

### Step 12: Present Combined Report to User

Format and display the findings; a first-time user should be pointed to option 5 (report only) before any cleanup runs:

```markdown
# Cleanup Analysis Report

**Project**: <project_name>  **Type**: <project_type>  **Generated**: <timestamp>

## File Organization Issues (Cleanliness Inspector)
## Development Standards Violations (Style Inspector)
## Prompt Verbosity Findings (Prompt Inspector — agents/ and commands/)

Each section: Critical, Major and Minor counts, then one line per finding (the prompt inspector's: file, severity, verbose_lines, recommendation).

## Summary

Total issues, estimated space to free, files to move, files to discard (archive, delete), style fixes.

## Cleanup Options

1. Execute all recommended actions (aggressive)
2. Execute only file organization (conservative)
3. Execute only critical/major issues
4. Review and approve individually (interactive)
5. Cancel and generate report only
```

### Step 13: Collect User Approval

Ask the user to pick one of the Step 12 options with one AskUserQuestion inside the turn, then build the approval context from the answer.

**Option 1: Execute all (aggressive)**: generate the approvals JSON mechanically from the combined report (Orchestrator Rules, 2):
1. Read `docs/clean/combined-report-{REQUEST_ID}.json`
2. Extract every finding from `findings` (cleanliness), `violations` (style), and `prompt_report.findings` (prompt verbosity; approved as action `fix_style` against the named `agents/` or `commands/` file)
3. For EACH finding, create one entry in `approved_actions` with `"approved": true`; set `rejected_actions` to an empty array
4. Record `total_issues_in_report` (the combined report's `combined_summary.total_issues`) and `total_approved_actions` (the count of `approved_actions`); Step 14 compares them

```json
{
  "request_id": "clean-YYYYMMDD-HHMMSS",
  "timestamp": "ISO-8601",
  "mode": "execute_all",
  "user_approvals": {
    "total_issues_in_report": 92,
    "total_approved_actions": 92,
    "approved_actions": [
      {"action_id": "finding_1", "source_report": "cleanliness|style|prompt", "source_finding_index": 0,
       "action": "move|delete|archive|fix", "description": "copied from finding",
       "location": "file:line or file path", "approved": true}
    ],
    "rejected_actions": []
  }
}
```

**Option 2**: file organization only (approve cleanliness findings, skip style and prompt). **Option 3**: critical/major only (filter by severity). **Option 4**: interactive (one AskUserQuestion per action). **Option 5**: report only (skip to the completion report). Options 2-4 apply the stated filter (by report type, severity or individual decision); only Option 1 is all-inclusive.

Save to: `docs/clean/user-approvals-{REQUEST_ID}.json`

### Step 14: Verify Cleanup Completeness (Option 1 Only)

Skip for Options 2-5. Compare `combined_summary.total_issues` in `docs/clean/combined-report-{REQUEST_ID}.json` with `total_approved_actions` in `docs/clean/user-approvals-{REQUEST_ID}.json`.

If the counts match, log "Completeness gate PASSED: {total_approved_actions} approved actions match {total_issues} combined report findings" and go on to Step 15.

If they differ, do not start Step 15 or Step 16: log "COMPLETENESS GATE FAILED: combined report total_issues {N}, approved actions {M}, {N - M} findings missing", return to Step 13 Option 1, regenerate the approvals JSON from the combined report, and run this gate again. The gate is never bypassed.

### Step 15: Create Safety Checkpoint

Before execution, create a safety checkpoint on `refs/checkpoints/<branch>`, not on HEAD (git blame hygiene); the checkpoint library handles the no-changes case (exit 0) and uses an isolated temp index, so the real staged area is untouched.

Run `bash "<HARNESS_ROOT>/hooks/checkpoint.sh" "Before /clean aggressive cleanup"`. Then read `refs/checkpoints/<branch>` and record the checkpoint commit via `bash "<HARNESS_ROOT>/scripts/orchestrator.sh" record-checkpoint docs/clean/context-{REQUEST_ID}.json <checkpoint_commit>`, which prints the `checkpoint_commit` Step 16 passes to the merge.

**Rollback**: the checkpoint lives on a detached ref, not as a HEAD ancestor. To recover individual files: `git checkout refs/checkpoints/$(git branch --show-current) -- <path>`

### Step 16: Invoke Cleaner with Approvals (DELEGATION ONLY)

The cleaner subagent executes every approved action; the orchestrator changes no project file (Orchestrator Rules, 1). Its one Bash call here prepares the cleaner's context, merging the approvals and the Step 15 checkpoint into it (writes `docs/clean/context-with-approvals-{REQUEST_ID}.json`):

```bash
python3 "<HARNESS_ROOT>/scripts/steps/clean-merge-approvals.py" {REQUEST_ID} <checkpoint_commit>
```

Invoke the cleaner subagent using the Agent tool:

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
{"task_id": null, "lane": null, "lane_set": null, "role": "cleaner", "pipeline": "clean", "profile": "ad_hoc", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this dispatch>", "artifacts": [{"kind": "markdown", "path": "docs/clean/cleanup-execution-{REQUEST_ID}.json", "identity_anchor": "{REQUEST_ID}", "terminal_line_regex": "^}$"}]}
</obligation>

Execute ALL approved_actions. Write results to docs/clean/cleanup-execution-{REQUEST_ID}.json."
```

The cleaner discards an approved archive or delete of a tracked path with a non-forced `git rm` and prints `DISCARDED <path> - recover: git checkout <sha> -- <path>` per path (`<sha>`: HEAD at the removal); `agents/cleaner.md` says what bash-safety passes, what the cleaner skips and the shape of its execution report.

The obligation declares only the execution report, so `hooks/pretool-tool-policy.py` refuses (exit 2) the destination of every move and rename and every `fix_style` edit the cleaner makes, and `hooks/pretool-git-privilege-guard.py` refuses (exit 2) its `git commit` unless the owner's `/allow` grants that command. A refusal is a hook rejection, not a failure: the cleaner lists each refused operation in `actions_refused` and runs the rest. When the cleaner returns, read the execution report; when `actions_refused` is not empty, follow the hook-rejection rule (Workflow Overview). A refused `git commit` allowed later is made by a re-dispatched cleaner, which commits and writes the push-gate token; left undone, the changes stay staged and uncommitted. An action that fails for another reason (its source is gone, or git refuses to remove a modified file) stays in `actions_failed` with that reason; the orchestrator does not retry it.

### Step 17: Verify Cleanup Results

Review git changes: check `git status`; when the execution report names a `cleanup_commit`, also `git diff --stat HEAD~1`. The summary states what happened, from the execution report, the owner's answers (Step 16) and these calls: a cleanup commit only when the report names one, else none.

```markdown
# Cleanup Execution Results

**Status**: <completed|partial>
**Actions**: X successful, Y failed, Z skipped, R refused by a hook (each with the owner's answer, or withdrawn, or a follow-up for a /dev cycle)

Changes: files moved; files discarded (the cleaner's DISCARDED lines, each with its recover command); style violations fixed; .gitignore updated.

- Checkpoint commit: <hash>
- Cleanup commit: <hash, or none: no change staged, or the commit refused (Step 16)>
- Files changed: X
- Ready for review: <yes with a cleanup commit, else no>

Next steps: review with `git diff HEAD~1` (a cleanup commit) or `git status`; with a cleanup commit the changes are committed (to publish: `/push`), without one nothing was committed and `git status` shows what the cleaner staged; to restore a discarded file run its DISCARDED line's recover command; detailed report: docs/clean/completion-{REQUEST_ID}.md
```

### Step 18: Generate Completion Report

Save to: `docs/clean/completion-{REQUEST_ID}.md`

```markdown
# Cleanup Completion Report

**Request ID**: clean-YYYYMMDD-HHMMSS
**Project**: <project_path>
**Type**: <project_type>
**Executed**: <timestamp>
**Status**: <completed|partial>

## Inspection Summary

Findings per inspector (cleanliness, style, prompt): total, critical, major, minor.

## Actions Executed

File organization (files moved, files discarded with git rm and their DISCARDED lines, files renamed) and style fixes, each with its count.

## Results

### Successful (X actions)
<list of successful actions>

### Failed (Y actions)
<list of failed actions with reasons>

### Skipped (Z actions)
<list of skipped actions with reasons>

### Refused by a hook (R actions)
<list of refused actions: exact operation, the hook's output, the owner's answer, withdrawn, or a follow-up for a /dev cycle>

## Summary Statistics

Space freed; files moved, archived, deleted; style fixes; git commits: <the checkpoint, plus the cleanup commit when the execution report names one>

## Git Information

- Checkpoint commit: <hash>
- Cleanup commit: <hash>
- Branch: <branch>
- Files changed: X
- Recovery: each DISCARDED line's recover command

## Related Files

The `docs/clean/` files of this request: context, cleanliness, style and combined reports, user approvals, execution report.
```
