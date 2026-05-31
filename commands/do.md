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

Before invoking `/close`, the agent MUST write `docs/dev/do-report-<session-id>.json`. The session-id comes from the consent flag `/tmp/claude-orchestrator-consent-<session-id>.flag`. Use the same timestamp as the task-id so `/close <session-id>` resolves it.

```json
{
  "task_id": "<session-id>",
  "request_id": "<session-id>",
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

Then: `/close <session-id>` runs the normal QA path using the do-report as the source artifact. `--force` is no longer required.
