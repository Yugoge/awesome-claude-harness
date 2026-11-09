# Infra-Hook Eval Case infra-hook-010: posttool-metric-emitter.py

## Trigger
PostToolUse with matcher `Bash|Edit|Write`. Hook emits per-call
duration and outcome metrics to a local Prometheus textfile collector.

## Behavior Required
- Reads PostToolUse hook input JSON on stdin and extracts the
  duration if available in `tool_response.duration_ms`.
- Increments a per-tool counter and records a histogram observation
  in `/var/lib/node_exporter/textfile_collector/claude_tools.prom`.
- Uses atomic write via temp file + rename to prevent collector reads
  from observing partial files.
- Bucket boundaries for the histogram are documented constants:
  `[10, 50, 100, 500, 1000, 5000, 30000]` milliseconds.
- Falls back to silent no-op if the textfile collector directory is
  absent (e.g., on developer workstation).

## Exit Code Contract
- exit 0: metric emitted OR silently no-op'd because collector dir is
  absent.
- exit 2: write failed despite collector dir present (disk full,
  permission denied).

## Acceptance
- AC-1: counter `claude_tool_calls_total{tool="Bash"}` increments by
  exactly 1 per Bash invocation.
- AC-2: temp-file rename leaves no `.tmp` artifact in the collector
  directory after success.
- AC-3: missing collector dir yields exit 0 with no file created.
