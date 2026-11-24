#!/usr/bin/env bash
# userprompt-harness-switch.sh — UserPromptSubmit: the owner's typed /harness off|on|status.
# The one harness hook that runs while the harness is off: it is the switch, not the harness, so
# it has no harness_switch guard. A /harness prompt (or, while off, a /dev-overnight wake) goes to
# scripts/harness-switch, which switches and reports (commands/harness.md). Any other prompt goes
# there only when this finds, with builtins and a `stat` per candidate: (a) while on, that this
# session's process (CLAUDE_PID) still has the token /harness on made for it (.harness-switch/late/
# <pid>-<start>; the late start removes it, so it runs once) and never ran the harness's
# SessionStart hooks, as the .owner that session-scratch-init.sh writes names another process (it
# started while off): --late, they run now; (b) a tasks directory of this session on a tmpfs, where the CLI may keep its command output:
# the program decides and prints the line. Else it exits 0, printing nothing.
payload="$(cat)"
here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
. "$here/lib/harness_switch.sh"
sid='' late='' go=''
[[ $payload =~ \"session_id\":\ *\"([0-9A-Za-z_-]+)\" ]] && sid=${BASH_REMATCH[1]}
if [ -n "$sid" ] && [[ ${CLAUDE_PID:-} =~ ^[0-9]+$ ]] && ! harness_switch_off; then
  { stat=$(< "/proc/$CLAUDE_PID/stat"); } 2>/dev/null
  read -ra f <<<"${stat##*) }"
  if [ -e "$here/../.harness-switch/late/$CLAUDE_PID-${f[19]:-}" ]; then
    { owner=$(< "${TMPDIR:-/var/tmp/claude-scratch}/$sid/.owner"); } 2>/dev/null
    [[ $owner == *"\"pid\": \"$CLAUDE_PID\", \"pid_start_time\": \"${f[19]:-}\""* ]] || late=--late go=1
  fi
fi
if [ -z "$go" ] && [ -n "$sid" ]; then
  for t in "${CLAUDE_CODE_TMPDIR:-/tmp}" "${TMPDIR:-/tmp}" /tmp; do
    for t in "$t"/claude-[0-9]*/*/"$sid"/tasks; do
      [ "$(stat -f -c %T "$t" 2>/dev/null)" = tmpfs ] && go=1
    done
  done
fi
case "$payload" in
  *harness*) go=1 ;;
esac
[ -n "$go" ] || exit 0
exec python3 "$here/../scripts/harness-switch" hook $late <<<"$payload"
