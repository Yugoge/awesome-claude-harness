---
description: End this session's /dev-overnight before its end time. Typed by the human only — the typed /stop itself releases the time-lock; agents cannot self-stop.
disable-model-invocation: true
---

# /stop — Overnight Lock Release

The human's exit from this session's /dev-overnight before its end time. The human-typed `/stop` record in the session's transcript is the release: from it on, the time-lock lets the session stop with no closeout check and publishes the `cancelled_by_user` receipt, the loop prints no further cycle, and the AskUserQuestion deny lifts. Nothing an agent writes (a state field, a token, a file) releases the lock, and agents cannot self-invoke the wrapper (user-intent sentinel guard, see Implementation).

## Usage

```
/stop
```

No arguments. Acts on this session's own overnight state only.

## What it does

1. Typing `/stop` releases this session's time-lock; the next stop attempt succeeds.
2. The wrapper records `current_phase: completed` in this session's overnight state (found from the main checkout, a worktree or a fresh clone) and releases its isolation fields. It leaves `end_time` as it was.

## What it does NOT do

- Does NOT remove the worktree (preserved for review/merge — use `/merge` when ready)
- Does NOT delete the state file (left in place for cycle log inspection)
- Does NOT touch in-flight subagents (kill those manually if needed)

## Implementation

The orchestrator calls the wrapper exactly once:

```bash
bash "${CLAUDE_HOME:-$HOME/.claude}/hooks/stop.sh"
```

Then, as the last step, where this session scheduled the overnight wake (dev-overnight.md Step 0), call `CronDelete` with the job id that wake's `CronCreate` returned: a wake left scheduled would fire into the stopped session, and the time-lock refuses the session's Stop until it is deleted.

The wrapper invokes `<HARNESS_ROOT>/scripts/break-overnight-lock.py`. Sentinel enforcement (written at `<state dir>/claude-stop-userintent-<sid>.flag` by `prompt-workflow.py` on user-typed `/stop`; consumed by the PreToolUse hook before the wrapper runs) prevents agent self-invocation.

## Why this command exists

The `/dev-overnight` time-lock holds the session until its end time by design. The human's exits are interrupting the session and typing `/stop`; editing the state file by hand releases nothing.
