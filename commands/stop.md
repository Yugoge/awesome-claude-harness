---
description: Cancel the current active ordinary Codex /dev or /redev workflow. Human exact-command invocation only.
disable-model-invocation: true
---

# /stop — Typed Codex Workflow Cancellation

Cancels only the current root thread's active ordinary `/dev` or `/redev` workflow. The registered Codex `UserPromptSubmit` hook authenticates the exact root transcript event and records an audited `user_cancelled` terminal outcome synchronously. The model does not execute a shell helper.

## Usage

```
/stop
```

No arguments, comments, prefixes, or suffixes. Only the exact standalone `/stop` command is accepted. Agent, forked, replayed, remapped, malformed, and non-latest prompt events fail closed.

## What it does

1. Binds the prompt to the current root Codex session transcript and exact workflow state.
2. Issues and atomically claims a dedicated, single-use `workflow_cancel` grant.
3. Preserves plan, agent, checkpoint, barrier, unsupported, and prior gate facts.
4. Persists an audited schema-revision-2 cancellation extension with `status: user_cancelled`.
5. Allows the next Stop because the workflow is cancelled, never because its plan was fabricated as complete.

## What it does NOT do

- Does NOT mark todos, plan steps, agents, QA, barriers, or checkpoints complete.
- Does NOT use or consume `/allow` grants or Claude stop sentinels.
- Does NOT fall back to the latest workflow or cancel another session.
- Does NOT modify the inactive `/root/.codex/awesome-codex-harness` migration target.
- Does NOT claim `/dev-overnight` process cancellation. That path remains `blocked_capability` until a typed external supervisor proves queue and process ownership.

## Implementation

There is no model-side implementation command. `/root/.codex/hooks/codex_native_harness.py` performs cancellation during the authenticated `UserPromptSubmit` event. The active Claude compatibility wrapper skips only `prompt-workflow.py` after verifying the same native terminal result, so it cannot mint `/tmp/claude-stop-userintent-*.flag` for this path.

## Why this command exists

Ordinary Codex workflows need an explicit cancellation outcome distinct from completion. A human must be able to terminate an incomplete `/dev` or `/redev` without corrupting its evidence, while agents and compatibility helpers remain unable to manufacture authority.
