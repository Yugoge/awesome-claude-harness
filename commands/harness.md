---
description: Switch the whole harness off, back on, or show its state - /harness off | on | status. Typed by the owner only; the UserPromptSubmit hook switches before the agent sees the prompt, and an agent has no path to it.
disable-model-invocation: true
argument-hint: "off | on | status"
summary: "Switch the whole harness off or back on for this harness home, or show its state; on restores exactly what off removed."
group: Control
---

# /harness — the owner's switch

The switch already ran when this prompt arrived: the owner's typed `/harness ...` is handled by `hooks/userprompt-harness-switch.sh`, a UserPromptSubmit hook, which runs `scripts/harness-switch` and hands you its report as context starting with `HARNESS SWITCH`. Nothing an agent does switches the harness: the command carries `disable-model-invocation: true` and a `Skill(harness:*)` deny, and while the harness is on, `hooks/pretool-harness-switch-guard.py` refuses every other path (the switch's program or state, the harness's settings files, a settings `disableAllHooks`, a scheduled or sent prompt that types `/harness`).

## What you do

1. Print the report verbatim, as one block. Do not rerun, repair or explain it away; if it names a partial state, the owner's next `/harness off` or `/harness on` finishes it.
2. After `/harness off` only: if this session scheduled a `/dev-overnight` wake (a `CronCreate` whose prompt starts with `[awesome-claude-harness/overnight-wake-v1]`), call `CronDelete` with that job's id. Look it up with `CronList` if you need to. While the harness is off, the hook refuses the wake's prompts anyway.
3. Run nothing else, and end the turn.

## What each argument does

- `off`: from the moment it is typed, no harness hook runs, for any event, in this session and every other one in this home. Checkpoint snapshots, the git-fswatch sync, the landing, automatic pushes and the keystone are inert too. A `/dev-overnight` run that started before it is over. From the next session on, settings.json has no harness hooks, env vars or permission rules, and the session loads no harness `CLAUDE.md`, commands (but `/harness`), agents or skills. MCP servers, plugins, login, credentials, session history and the owner's own settings stay as they are.
- `on`: brings back exactly what off removed, plus any change the owner made while off. After a pull made while off, it brings back the newly pulled version.
- `status` (also `/harness` alone): on, off or partial; since when; which harness home and config dir it covers; whether a restart is still needed for the full effect.
