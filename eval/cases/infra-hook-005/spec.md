# Infra-Hook Eval Case infra-hook-005: pretool-edit-confirm.py

## Trigger
PreToolUse with matcher `Edit`. Hook gates Edit tool invocations to
ensure the target file was Read in the same conversation transcript.

## Behavior Required
- Reads PreToolUse hook input JSON on stdin.
- Resolves the absolute path of `tool_input.file_path`.
- Consults a per-session read-tracker file at
  `/tmp/claude-read-tracker-<session_id>.json` for the list of files
  the agent has already Read.
- Allows Edit when the target appears in the read-tracker list.
- Blocks Edit when target was never Read in this session and emits
  stderr instructing the caller to Read first.
- Special-cases `/dev/null` and `/tmp/throwaway-*` as exempt.

## Exit Code Contract
- exit 0: target was previously Read in this session OR is exempt.
- exit 2: target was never Read; caller must invoke Read first.

## Acceptance
- AC-1: rejects Edit on `/root/foo.py` when read-tracker is empty
  with exit 2.
- AC-2: allows Edit on `/root/foo.py` after a synthetic Read entry is
  inserted into the tracker.
- AC-3: allows Edit on `/dev/null` with exit 0 unconditionally.
