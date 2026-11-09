# Infra-Hook Eval Case infra-hook-011: stop-cleanup-temp.py

## Trigger
Stop hook (no matcher). Hook fires when the orchestrator session ends
or is interrupted.

## Behavior Required
- Reads Stop hook input JSON on stdin to retrieve the session ID.
- Identifies temp files belonging to this session via the naming
  convention `/tmp/claude-*-<session_id>*`.
- Removes those temp files using `pathlib.Path.unlink(missing_ok=True)`
  to avoid races with concurrent cleanup.
- Preserves files older than the session start time (cross-session
  artifacts must not be touched).
- Emits a summary line to stderr: number of files removed and total
  bytes reclaimed.

## Exit Code Contract
- exit 0: cleanup completed (zero or more files removed cleanly).
- exit 2: a removal raised an unexpected error (not `FileNotFoundError`).

## Acceptance
- AC-1: temp files matching the session pattern are removed; verified
  by `ls /tmp/claude-*-<session_id>*` returning empty.
- AC-2: temp files belonging to a different session are untouched.
- AC-3: stderr summary line includes both `files_removed` and
  `bytes_reclaimed` integer values.
