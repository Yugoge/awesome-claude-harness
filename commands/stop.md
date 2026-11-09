---
description: End this session's /dev-overnight before its end time. Typed by the human only — the typed /stop itself releases the time-lock; agents cannot self-stop.
disable-model-invocation: true
---

# /stop — Overnight Lock Release

The human's exit from an armed command, besides interrupting the session. The human-typed `/stop` record in the session's transcript is the release; nothing an agent writes (a state field, a token, a file) releases anything. No arguments: it acts on this session's own overnight state only. The Stop gate (`hooks/stop-command-gate.py`) reads the record and `hooks/pretool-wrapper-userintent.py` refuses an agent's own run of the wrapper; `docs/ENFORCEMENT-LEDGER.md` lists both as advisory.

## What it does

1. The typed `/stop` opens a span no Stop gate holds: it ends any gated command (`/dev`, `/do`, `/close`, `/commit`, ..., even one whose gate is broken). After `/dev-overnight` the time-lock lets the session stop with no closeout check and publishes the `cancelled_by_user` receipt, the loop prints no further cycle, and the AskUserQuestion deny lifts. After the wrapper and the `CronDelete` below, the next stop attempt succeeds.
2. The wrapper records `current_phase: completed` in this session's overnight state (found from the main checkout, a worktree or a fresh clone) and releases its isolation fields. It leaves `end_time` as it was.

It does NOT remove the worktree (use `/merge` when ready), delete the state file (the cycle log stays for inspection) or touch in-flight subagents (kill those by hand).

## Implementation

Call the wrapper exactly once:

```bash
bash "<HARNESS_ROOT>/hooks/stop.sh"
```

Then, as the last step, where this session scheduled the overnight wake (dev-overnight.md Step 0), call `CronDelete` with the job id that wake's `CronCreate` returned: a wake left scheduled would fire into the stopped session, and the time-lock refuses the session's Stop until it is deleted.
