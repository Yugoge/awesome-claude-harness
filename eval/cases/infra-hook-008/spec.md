# Infra-Hook Eval Case infra-hook-008: posttool-session-snapshot.py

## Trigger
PostToolUse with matcher `Bash`. Hook fires after any Bash invocation
to capture session state for cross-session debugging.

## Behavior Required
- Reads PostToolUse hook input JSON on stdin and extracts the executed
  command, exit code, and tool output excerpt.
- Appends a JSON-line entry to
  `~/.claude/sessions/<session_id>/bash-history.jsonl`.
- Truncates `tool_output` excerpts at 4000 characters to bound disk
  usage.
- Compresses the session-history file with gzip if it exceeds 10 MB
  using a side-rotation strategy.
- Never blocks the calling tool — exit 0 even when its own append
  fails (best-effort).

## Exit Code Contract
- exit 0: snapshot appended successfully OR best-effort append failed
  (non-blocking design).
- exit 2: input JSON is malformed (only structural-error case).

## Acceptance
- AC-1: file `bash-history.jsonl` gains exactly one line per Bash
  invocation.
- AC-2: tool output longer than 4000 chars is truncated and an
  `excerpt_truncated: true` field is added.
- AC-3: malformed input JSON produces exit 2 with stderr naming the
  parse error.
