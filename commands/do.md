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

### Step 5: Write do-report

End every `/do` with a do-report at `docs/dev/do-report-<TASK_ID>.json`. You write it whole (the template below; no hook pre-writes it): `do.status` `"completed"`, `do.summary` saying what was done, `do.files_modified`/`do.files_created` filled. NEVER report unfinished work as completed: when the task cannot be finished as asked, ask the user in this turn how to go on (below).

The gate: the Stop gate (`hooks/stop-command-gate.py`) holds this `/do` until the report validates against `schemas/do-report.v1.json`, `do.status` is `"completed"` and its file lists are exact (below). It writes and deletes nothing: only finishing the report releases it. A decision only the user can make is asked in this turn with AskUserQuestion; the answer releases no gate.

**`TASK_ID`** is the id in the hook's `[/do] task-id minted: <id>` line: a reserved `YYYYMMDD-HHMMSS` timestamp. The hook is the only mint: never mint one, and never take the newest `claude-orchestrator-consent-*.flag` in the state dir (two concurrent `/do` sessions would alias onto one id and overwrite each other's do-reports). To read it back for the CURRENT session (after a compaction):
1. `SID = $CLAUDE_CODE_SESSION_ID` (fallback `$CLAUDE_SESSION_ID`).
2. Read `task_id` from the session-keyed sidecar `claude-do-task-$SID.json` in the state dir (`$CLAUDE_STATE_DIR` when that is an absolute path, else `/tmp`: `. ~/.claude/hooks/lib/harness_state_dir.sh; harness_state_dir`), the path the minted line printed.

Use this `TASK_ID` for the do-report filename AND every downstream `/close $TASK_ID` / `/commit $TASK_ID`.

```json
{
  "report_version": 1,
  "task_id": "<TASK_ID>",
  "request_id": "<TASK_ID>",
  "source": "do",
  "request": "<original /do args verbatim>",
  "profile": "do",
  "expected_absent": ["qa-report", "dev-report", "ticket", "context", "completion"],
  "do": {
    "status": "completed",
    "summary": "<1-2 sentence description of what was accomplished>",
    "files_modified": ["<file1>", "<file2>"],
    "files_created": []
  }
}
```

`report_version: 1` declares the schema the gate validates; keep it, and keep `expected_absent`: it is how the close QA's e2e gate (`hooks/subagentstop-e2e-enforce.py`) knows a /do task has no qa-report.

`files_modified` and `files_created` list exactly the project files you changed after the `/do` prompt, with an edit tool or a Bash command naming them (outside `docs/dev/`, `.claude/dev-registry/` and `.claude/scratch/`). The gate compares them with the transcript's record of your calls; never derive them from `git diff` (session-unaware, wrong under parallel `/do` sessions). A created file goes in `files_modified` too: `/close` inspects only the files listed there.

Then: `/close <TASK_ID>` runs the normal QA path using the do-report as the source artifact. `--force` is no longer required.
