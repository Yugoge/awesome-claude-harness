# Infra-Hook Eval Case infra-hook-003: pretool-bash-safety.sh

## Trigger
PreToolUse with matcher `Bash`. Hook is the central bash-command gate
described in `~/.claude/CLAUDE.md` Safety Enforcement section.

## Behavior Required
- Reads hook input JSON on stdin and extracts `tool_input.command`.
- Applies the categorized rule set: session-critical scripts,
  destructive disk operations, docker daemon control, production
  container lifecycle, and named-process termination.
- Emits a one-line stderr describing the matched category and the
  command excerpt that triggered the match.
- Does NOT modify or read any other file outside `/dev/stdin` and
  optional log append at `~/.claude/logs/bash-safety.log`.
- Returns control quickly (under 100 ms) so it does not block legitimate
  commands.

## Exit Code Contract
- exit 0: command does not match any forbidden category.
- exit 2: command matches at least one forbidden category; stderr names
  the category and the offending substring.

## Acceptance
- AC-1: blocks `rm -rf /var/lib/docker` with stderr citing
  "destructive disk operations".
- AC-2: blocks `docker stop happy-server` with stderr citing
  "production container lifecycle".
- AC-3: allows benign command `ls /tmp` with exit 0.
