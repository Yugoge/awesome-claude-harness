#!/usr/bin/env bash
# userprompt-harness-switch.sh — UserPromptSubmit: the owner's typed /harness off|on|status.
# The one harness hook that runs while the harness is off: it is the switch, not the harness, so
# it has no harness_switch guard. For any other prompt it exits 0 at once, printing nothing and
# starting no interpreter; a /harness prompt (or, while off, a /dev-overnight wake) goes to
# scripts/harness-switch, which switches and reports (commands/harness.md).
payload="$(cat)"
case "$payload" in
  *harness*) ;;
  *) exit 0 ;;
esac
exec python3 "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../scripts/harness-switch" hook <<<"$payload"
