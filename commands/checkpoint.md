---
description: "Checkpoint Command"
disable-model-invocation: true
---

# Checkpoint Command

Snapshot current progress to a `refs/checkpoints/<branch>` safety ref — the branch HEAD is never moved and your working branch is never pushed; the checkpoint ref itself is background-pushed (rate-limited to 1/30s per repo, without `-f`).

## Usage

```bash
bash ~/.claude/hooks/checkpoint.sh
```

This command will:
1. Check for any uncommitted changes
2. Snapshot the working tree into an ISOLATED temp index (`GIT_INDEX_FILE`) — the real
   index and the branch HEAD are never touched
3. Write the snapshot to `refs/checkpoints/<branch>` (a safety ref that never advances HEAD)
4. Background-push the checkpoint ref, rate-limited to 1/30s per repo and without `-f` (the
   working branch HEAD is never pushed; only the `refs/checkpoints/<branch>` ref is)

## When to use

- Before taking a break
- After completing a significant change
- When you want to ensure everything is backed up
- As a safety checkpoint during long sessions

## Environment Variables

- `GIT_CHECKPOINT_MESSAGE`: Custom message prefix (default: "checkpoint")

## Examples

```bash
# Quick checkpoint
bash ~/.claude/hooks/checkpoint.sh

# With custom message
GIT_CHECKPOINT_MESSAGE="Before refactoring" bash ~/.claude/hooks/checkpoint.sh
```
