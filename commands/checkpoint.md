---
description: "Checkpoint Command"
disable-model-invocation: true
---

# Checkpoint Command

Snapshot current progress to a `refs/checkpoints/<branch>` safety ref — the branch HEAD is never moved and your working branch is never pushed. The checkpoint ref stays local unless `GIT_AUTO_PUSH` is exactly `1` (the shipped `settings.json` sets `0`); then it is pushed in the background, at most once per 30 seconds per repo, without `-f`.

## Usage

```bash
bash "<HARNESS_ROOT>/hooks/checkpoint.sh"
```

This command will:
1. Check for any uncommitted changes
2. Snapshot the working tree into an ISOLATED temp index (`GIT_INDEX_FILE`) — the real
   index and the branch HEAD are never touched
3. Write the snapshot to `refs/checkpoints/<branch>` (a safety ref that never advances HEAD)
4. Only when `GIT_AUTO_PUSH` is exactly `1`: push the checkpoint ref in the background, at most
   once per 30 seconds per repo and without `-f` (the working branch HEAD is never pushed; only the
   `refs/checkpoints/<branch>` ref is). Any other value, unset included, keeps the ref local, and the
   command says so

## When to use

- Before taking a break
- After completing a significant change
- When you want to ensure everything is backed up
- As a safety checkpoint during long sessions

## Environment Variables

- `GIT_CHECKPOINT_MESSAGE`: Custom message prefix (default: "checkpoint")
- `GIT_AUTO_PUSH`: `1` pushes the checkpoint ref (step 4); any other value keeps it local

## Examples

```bash
# Quick checkpoint
bash "<HARNESS_ROOT>/hooks/checkpoint.sh"

# With custom message
GIT_CHECKPOINT_MESSAGE="Before refactoring" bash "${CLAUDE_HOME:-$HOME/.claude}/hooks/checkpoint.sh"
```
