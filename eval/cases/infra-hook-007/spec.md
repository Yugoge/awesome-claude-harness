# Infra-Hook Eval Case infra-hook-007: posttool-auto-checkpoint.py

## Trigger
PostToolUse with matcher `Edit|Write|MultiEdit`. Hook fires after any
tool that mutates files in the working tree.

## Behavior Required
- Reads PostToolUse hook input JSON on stdin and extracts the modified
  file path from `tool_input`.
- Maintains a per-session counter of mutating tool calls in
  `/tmp/claude-checkpoint-counter-<session>.json`.
- When the counter reaches a configurable threshold (default 5),
  invokes `git add -A && git write-tree` to snapshot into
  `refs/checkpoints/<sanitized-branch>` per CLAUDE.md mechanism.
- Resets the counter to 0 after a successful snapshot.
- Never advances HEAD; only writes to the checkpoint ref.

## Exit Code Contract
- exit 0: success — counter incremented OR snapshot written cleanly.
- exit 2: snapshot attempt failed (git error); stderr names the git
  command and exit code.

## Acceptance
- AC-1: 5 sequential Edit invocations cause exactly one checkpoint
  ref update with exit 0 each time.
- AC-2: counter resets to 0 after snapshot; verified by reading the
  state file.
- AC-3: branch HEAD sha is unchanged before vs. after the snapshot.
