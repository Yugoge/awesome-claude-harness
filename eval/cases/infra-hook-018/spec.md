# Infra-Hook Eval Case infra-hook-018: standalone script — healthcheck-claude-infra.sh

## Trigger
Standalone bash script invoked manually, by a systemd timer, or by an
external monitoring poller. Not a Claude Code hook.

## Behavior Required
- Accepts one optional parameter: `OUTPUT_FORMAT` (positional 1,
  default `text`, allowed values `text` or `json`).
- Probes the following local resources and records pass/fail per probe:
  the `~/.claude/settings.json` file is readable and parseable, the
  `~/.claude/hooks/` directory exists with at least one executable
  hook script, the local tmpfs workspace symlink resolves, and
  `git status` run in that workspace exits zero.
- Aggregates the results and prints them in the requested format.
- Returns nonzero exit if any probe failed.
- Completes within 5 seconds even when the tmpfs is degraded.

## Exit Code Contract
- exit 0: all probes passed.
- exit 2: at least one probe failed; output names the failed probes.

## Acceptance
- AC-1: with all infra healthy, exit 0 and stdout/json reports
  `passed: 4, failed: 0`.
- AC-2: temporarily renaming `~/.claude/hooks/` causes exit 2 with the
  hooks-directory probe marked failed.
- AC-3: invoking with `OUTPUT_FORMAT=json` produces a parseable JSON
  object on stdout with a `probes` array.
