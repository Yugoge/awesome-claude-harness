---
description: Cancel active overnight time-lock + workflow-enforce so the session can terminate normally. User-invoked only — agents cannot self-stop.
disable-model-invocation: true
---

# /stop — Overnight Lock Release

Releases every active overnight session's time-lock and workflow-enforce so the conversation can stop normally. User-invoked emergency exit; agents cannot self-invoke (sentinel guard mirrors `/commit /push /merge`).

## Usage

```
/stop
```

No arguments. Operates on every `overnight-state-*.json` under `.claude/`.

## What it does

1. Backdates `end_time` on every active overnight-state file so `stop-overnight-timelock.py` releases.
2. Marks every todo in `~/.claude/todos/<sid>-agent-<sid>.json` as `completed` so the workflow-enforce hook releases.
3. Sets `current_phase: completed` on each state file.

After this, the next stop attempt succeeds.

## What it does NOT do

- Does NOT remove the worktree (preserved for review/merge — use `/merge` when ready)
- Does NOT delete the state file (left in place for cycle log inspection)
- Does NOT touch in-flight subagents (kill those manually if needed)

## Implementation

The orchestrator calls the wrapper exactly once:

```bash
bash ~/.claude/hooks/stop.sh
```

The wrapper invokes `~/.claude/scripts/break-overnight-lock.py`. Sentinel enforcement (written at `/tmp/claude-stop-userintent-<sid>.flag` by `prompt-workflow.py` on user-typed `/stop`; consumed by the PreToolUse hook before the wrapper runs) prevents agent self-invocation.

## Why this command exists

The `/dev-overnight` time-lock prevents premature termination by design — but several edge cases trap the user for hours despite no productive work being possible:

- Argparse rejects `+0.5h` and falls back to default 8h (no way to shorten)
- Step 1 dev-registry sentinel write fails on `.claude` symlink topology, blocking all forward progress
- Hook-edit guard prevents the orchestrator from fixing the blocking hook itself

In any of these cases, `/stop` is the user's emergency release valve. Manual fallback (edit state file by hand, kill session forcibly) remains available but is no longer required.
