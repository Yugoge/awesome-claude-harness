# Infra-Hook Eval Case infra-hook-009: posttool-log-collector.py

## Trigger
PostToolUse with matcher `*` (all tools). Hook centralizes structured
logging for downstream metric and audit analysis.

## Behavior Required
- Reads PostToolUse hook input JSON on stdin and extracts `tool_name`,
  `tool_input` (redacted), and `tool_response.exit_code` if present.
- Writes a single JSON-line entry to
  `~/.claude/logs/tool-events.jsonl` with ISO-8601 timestamp.
- Redacts secret-like fields from `tool_input`: any key matching
  `password`, `secret`, `token`, `api_key` is replaced with `***`.
- Uses an exclusive `flock` on the log file to prevent concurrent
  writers from interleaving partial lines.
- Skips logging when the tool name matches a configurable noise filter
  (e.g., `Read`, `Glob`, `Grep`).

## Exit Code Contract
- exit 0: log entry written or intentionally skipped.
- exit 2: lock acquisition timed out OR target log path unwritable.

## Acceptance
- AC-1: 100 concurrent invocations produce exactly 100 newline-
  delimited JSON entries with no interleaving.
- AC-2: redaction replaces `tool_input.api_key` value with `***` in
  the written entry.
- AC-3: `Read` invocations produce no entry when noise filter is
  enabled.
