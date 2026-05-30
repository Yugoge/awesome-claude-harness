---
description: Allow main agent to bypass orchestrator-gate restrictions for this turn (subagent-only operations become directly allowed). Auto-clears at stop.
disable-model-invocation: true
---

(hook-only command; body is not injected because of `disable-model-invocation: true`. This line exists so the body is never empty — see commands/dev-command.md for the empty-body API-400 lesson.)

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
