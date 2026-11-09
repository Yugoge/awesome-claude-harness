---
description: /redev is /dev when saving context: it re-enters the harness in the same conversation without repeating /dev's text and is /dev in every other respect (same arguments, steps, gates and artifacts; a fresh task id each invocation; no earlier cycle continued).
argument-hint: "[--codex] [--spec <path>] [<requirement>]"
disable-model-invocation: true
---

`/redev` is `/dev` when saving context: it re-enters the harness in this conversation without repeating the prompt. Run the `/dev` workflow for the requirement in `$ARGUMENTS`; its one difference is that it does not re-emit `/dev`'s text, which this conversation already holds. In every other respect it is `/dev`: same arguments, steps, gates, artifacts and checklist (`scripts/todo/redev.py` delegates to `scripts/todo/dev.py`), and the same rule that every requested outcome is delivered in this cycle, with no sequential phases or deferred parts.

- If this conversation does not hold `/dev`'s text (a compaction removed it, or `/dev` never ran here), read `<HARNESS_ROOT>/commands/dev.md` and follow it.
- The hooks start and gate it exactly as `/dev`, under a fresh task id each invocation. Text after `/redev` is always requirement text, never a task id: the cycle continues no earlier cycle and reuses none of its task id, artifact paths or acceptance criteria. An interrupted session is resumed with `/restart`.
- Bare `/redev` (no requirement text) binds the new cycle to the development need stated in this conversation that no earlier cycle has completed; when there is none, ask for the requirement as `/dev` does for empty arguments.
