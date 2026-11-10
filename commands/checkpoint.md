---
description: "Checkpoint Command"
disable-model-invocation: true
summary: "Snapshot the working tree to the safety ref `refs/checkpoints/<branch>` without moving HEAD, touching the index or pushing."
group: Ship
---

# Checkpoint Command

Snapshot the working tree to the safety ref `refs/checkpoints/<branch>`. The branch HEAD and the real index are never touched and the working branch is never pushed. Mechanism and recovery: `docs/reference/checkpoint-mechanism.md`.

## Usage

```bash
bash "<HARNESS_ROOT>/hooks/checkpoint.sh"
```

`GIT_CHECKPOINT_MESSAGE` replaces the default `checkpoint` prefix of the snapshot message:

```bash
GIT_CHECKPOINT_MESSAGE="Before refactoring" bash "${CLAUDE_HOME:-$HOME/.claude}/hooks/checkpoint.sh"
```

## Report back

Run the script once and relay what it printed:

- the ref, its new tip and the file count; "No changes to checkpoint" means no ref was written;
- whether the ref stayed local or a background push started (on only when the repository's `harness.autoPush` is true, else when `GIT_AUTO_PUSH` is `1`; the script prints which);
- on a non-zero exit, the error and the log path it names.
