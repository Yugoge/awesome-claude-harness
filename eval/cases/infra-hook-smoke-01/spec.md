# infra-hook-smoke-01

## Title
Author a PreToolUse hook that blocks `rm -rf` against `~/.claude/`

## Context
A subagent recently came close to running `rm -rf ~/.claude/hooks/` while
trying to "clean up" stale files. We need a defense-in-depth PreToolUse
hook that intercepts any Bash command whose normalized form contains
`rm -rf` AND targets a path under `~/.claude/`, and exits non-zero with a
clear message.

## Files In Scope
- New hook: `~/.claude/hooks/pretool-block-claude-rm.py`.
- Settings registration in `~/.claude/settings.local.json` (orchestrator
  applies the settings change in a separate task; dev should provide the
  recommended JSON snippet only).

## Behavior
- Reads PreToolUse hook input JSON from stdin.
- If `tool_name == "Bash"` and the command matches the rule, exits 2 with
  a stderr message naming the offending command.
- Otherwise exits 0.

## Verification
- Unit-style harness: `echo '<json>' | python3 hook.py; echo $?` for both
  the blocked case (expect exit 2) and the allowed case (expect exit 0).
- Hook test exit codes captured in the dev report.
