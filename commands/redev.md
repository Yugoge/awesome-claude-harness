---
description: /redev is /dev when saving context — the /dev workflow (same arguments, steps, gates and artifacts) without re-emitting its text, under a fresh task id on every invocation. Pass --codex to enable adversarial codex consultation on each subagent's draft; default is self-review only.
argument-hint: "[--codex] [--spec <path>] [<requirement>]"
disable-model-invocation: true
---

`/redev` is `/dev`: run `commands/dev.md` for the requirement in `$ARGUMENTS`, with its argument parsing (`--codex`, `--spec <path>`, `--no-graphify`; Steps 1 and 2), its 17-step checklist (`scripts/todo/redev.py` returns `scripts/todo/dev.py`'s), its steps, gates and artifact names.

- It only saves context: it does not re-emit /dev's text, which this conversation already holds. When the conversation no longer holds it (a compaction removed it), read `~/.claude/commands/dev.md` and follow it.
- The `UserPromptSubmit` hook (`hooks/prompt-workflow.py`) starts it exactly as `/dev`, under a fresh task id and registry on every invocation, and every hook treats it as `/dev`. There is no task-id form: text after `/redev` is requirement text, and the cycle continues no earlier cycle and reuses none of its task id, artifact paths or acceptance criteria. An interrupted session is resumed with `/restart`.
- Bare `/redev` (no requirement text) binds the new cycle to the development need stated in this conversation that no earlier cycle has completed; when there is none, ask for the requirement as `/dev` Step 1 does.
