---
description: Allow main agent to bypass orchestrator-gate restrictions for this turn (subagent-only operations become directly allowed). Auto-clears at stop.
disable-model-invocation: true
---

(hook-only: `disable-model-invocation: true` suppresses a standalone AI turn, but the body IS injected into context. This line exists so the body is never empty — see commands/dev-command.md for the empty-body API-400 lesson.)

## Argument parsing

```
ORIGINAL_ARGUMENTS = $ARGUMENTS                           (preserve verbatim for do-report.request)
CODEX_REQUESTED = $ARGUMENTS contains literal token "--codex"
TASK = $ARGUMENTS with "--codex" token removed (trimmed)
```

If `TASK` is empty, ask the user for the task before proceeding.

## Workflow

### Step 1: Understand requirements

Read `TASK`. In one sentence state: what is being changed and what the end state looks like.

### Step 2: Develop

Do the work. Gate bypass is active — all tools are available. Edit files, run commands, make changes as needed.

### Step 3: Codex audit (only when `CODEX_REQUESTED = true`)

Invoke `Skill(skill="codex", args=<audit prompt>)` scoped to Step 2's changes:

```
USER REQUIREMENT: <TASK>
SCOPE: bugs that prevent or threaten this requirement.
OUT OF SCOPE: pre-existing issues, style preferences, unrelated enhancements.
```

Classify findings per `commands/codex.md` Rule 3. Fix `in_scope_real_bug` items; defer `out_of_scope` to a separate cycle.

If codex fails (quota/timeout/parse): record `codex_consult: {status: "<failed_quota|failed_timeout|failed_parse>", note: "<verbatim error>"}` in the do-report and proceed.

### Step 4: Summary

State what changed, which files were modified, and (if Step 3 ran) whether codex found any blocking issues.

## Before /close: write do-report

Before invoking `/close`, the agent MUST write `docs/dev/do-report-<TASK_ID>.json`.

**Resolve `TASK_ID` deterministically for the CURRENT session** — do NOT run `ls -t /tmp/claude-orchestrator-consent-*.flag | head -1` (that returns the globally-newest flag, so two concurrent `/do` sessions alias onto ONE id and silently overwrite each other's do-reports — the cross-task data-loss bug this resolution exists to prevent). Instead:
1. `SID = $CLAUDE_CODE_SESSION_ID` (fallback `$CLAUDE_SESSION_ID`).
2. Read the session-keyed sidecar `/tmp/claude-do-task-$SID.json` (minted by the `/do` consent hook in `hooks/prompt-workflow.py`) and use its `task_id` field — a globally-unique, reservation-backed `YYYYMMDD-HHMMSS` timestamp.
3. Fallback ONLY if the sidecar is missing/unreadable (the hook didn't run): mint atomically using the SAME flat reservation namespace the hook uses — `while :; do TS=$(date -u +%Y%m%d-%H%M%S); if (set -o noclobber; : > "/tmp/claude-do-resv-$TS") 2>/dev/null; then break; fi; sleep 1; done; TASK_ID=$TS`. `set -o noclobber` makes `>` an O_EXCL create, so the reservation is atomic across parallel sessions — do NOT use a non-atomic "does `do-report-$TASK_ID.json` already exist?" check, which two fallbacking sessions can both pass before either writes.

Use this `TASK_ID` for the do-report filename AND every downstream `/close $TASK_ID` / `/commit $TASK_ID`.

```json
{
  "task_id": "<TASK_ID>",
  "request_id": "<TASK_ID>",
  "source": "do",
  "request": "<original /do args verbatim>",
  "do": {
    "status": "completed",
    "summary": "<1-2 sentence description of what was accomplished>",
    "files_modified": ["<file1>", "<file2>"],
    "files_created": []
  }
}
```

`files_modified` and `files_created` MUST be filled by the agent from its own knowledge of what it changed — NOT derived from `git diff` (git diff is session-unaware and breaks under parallel /do sessions).

**Important**: `/close` uses `files_modified` as the cycle-diff file list for inspector dispatch. Newly created files that need inspector coverage MUST also appear in `files_modified` (in addition to `files_created`). Omitting a new file from `files_modified` means it will not be inspected.

Then: `/close <TASK_ID>` runs the normal QA path using the do-report as the source artifact. `--force` is no longer required.
