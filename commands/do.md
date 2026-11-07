---
description: Allow main agent to bypass orchestrator-gate restrictions for this turn (subagent-only operations become directly allowed). The next prompt clears it.
disable-model-invocation: true
---

(Human-only: `disable-model-invocation: true` keeps the model from invoking /do itself. When the owner types it, `hooks/prompt-workflow.py` writes the consent flag and mints the task id, and this body reaches the model with the typed arguments. The consent lasts this turn: the next prompt that is not /do clears it. It does not cover `git commit`, `git push` or a merge into the protected branch, which land through /close then /commit, /push and /merge (`hooks/pretool-git-privilege-guard.py`).)

## Argument parsing

```
ORIGINAL_ARGUMENTS = $ARGUMENTS                           (preserve verbatim for do-report.request)
CODEX_REQUESTED = $ARGUMENTS contains literal token "--codex"
TASK = $ARGUMENTS with "--codex" token removed (trimmed)
```

If `TASK` is empty, ask the user for the task with AskUserQuestion inside the turn before proceeding (a typed reply would be a new prompt, which ends the /do consent).

## Workflow

### Step 1: Understand requirements

Read `TASK`. In one sentence state: what is being changed and what the end state looks like.

### Step 2: Develop

Do the work. The orchestrator gate lets every tool through this turn except EnterPlanMode and ExitPlanMode, which it always blocks; every other hook still applies. Edit files, run commands, make changes as needed.

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

Every `/do` invocation MUST end with a do-report at `docs/dev/do-report-<TASK_ID>.json` — this is no longer deferred to "before /close". You write the whole report (the template below; no hook pre-writes it) once the task is done: `do.status` `"completed"`, `do.summary` and `do.files_modified`/`do.files_created` filled. /do has that one terminal. A decision only the owner can make (an operation a hook refuses included) is one specific AskUserQuestion inside the turn, naming it; then the work continues. NEVER report unfinished work as completed.

Enforcement: `hooks/stop-do-report-gate.py` (Stop hook) checks this report against `schemas/do-report.v1.json` plus its status and summary shape at session stop. Its default mode is block (`DO_REPORT_GATE_MODE` unset): an absent, non-terminal or malformed report blocks the stop. Any other value (`advisory`, `off`) allows the stop. The gate checks shape only — it never derives `files_modified` from git, and it never writes the report for you.

**Resolve `TASK_ID` deterministically for the CURRENT session** — do NOT list the newest `claude-orchestrator-consent-*.flag` in the state dir (that returns the globally-newest flag, so two concurrent `/do` sessions alias onto ONE id and silently overwrite each other's do-reports — the cross-task data-loss bug this resolution exists to prevent). Instead:
1. `SID = $CLAUDE_CODE_SESSION_ID` (fallback `$CLAUDE_SESSION_ID`).
2. Read the session-keyed sidecar `claude-do-task-$SID.json` in the hook state dir, the path the `/do` consent hook in `hooks/prompt-workflow.py` printed when it minted it (`. ~/.claude/hooks/lib/harness_state_dir.sh; harness_state_dir` prints the state dir) and use its `task_id` field — a globally-unique, reservation-backed `YYYYMMDD-HHMMSS` timestamp. The hook is the only mint: it writes the sidecar in the same step as the consent flag, so never mint an id yourself.

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

`report_version: 1` declares `schemas/do-report.v1.json`; the stop gate validates against it (keep the field — an unversioned report skips schema validation but still fails the stop gate's shape check if malformed). Keep `expected_absent` too: it is how the close QA's e2e gate (`hooks/subagentstop-e2e-enforce.py`) knows a /do task has no qa-report.

`files_modified` and `files_created` MUST be filled by the agent from its own knowledge of what it changed — NOT derived from `git diff` (git diff is session-unaware and breaks under parallel /do sessions).

**Important**: `/close` uses `files_modified` as the cycle-diff file list for inspector dispatch. Newly created files that need inspector coverage MUST also appear in `files_modified` (in addition to `files_created`). Omitting a new file from `files_modified` means it will not be inspected.

Then: `/close <TASK_ID>` runs the normal QA path using the do-report as the source artifact. `--force` is no longer required.
