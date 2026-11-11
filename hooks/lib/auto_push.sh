#!/usr/bin/env bash
# auto_push.sh -- harness_auto_push, the one reader of the per-repository push switch.
#
# Source it, then call:  harness_auto_push <repo-dir>   (exit 0 = push, anything else = no push)
# D1 as amended: the repository's LOCAL git config harness.autoPush decides first. A value git
# reads as true pushes; false, or a value git cannot read as a boolean, does not. Unset, the global
# GIT_AUTO_PUSH decides as before: exactly "1" pushes. A global or system harness.autoPush is not
# read, so the one global switch stays GIT_AUTO_PUSH. Every automatic push path calls this:
# _checkpoint_rate_limited_push (lib/checkpoint-core.sh), safe_push (git-fswatch.sh), the
# initial push of session-git-init.sh, and the post-commit hooks copied into repositories
# (git-hooks/post-commit-auto-push and install-protection-all.sh's combined hook), which load
# it from ${CLAUDE_HOME:-$HOME/.claude}/hooks/lib/.

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/harness_switch.sh" 2>/dev/null \
  || harness_switch_off() { return 1; }

harness_auto_push() {
  local v rc
  harness_switch_off && return 1  # /harness off: no automatic push of any kind
  v="$(git -C "${1:-.}" config --local --type=bool --get harness.autoPush 2>/dev/null)"
  rc=$?
  case "$rc:$v" in
    0:true) return 0 ;;
    1:) [ "${GIT_AUTO_PUSH:-}" = "1" ] ;;  # git exits 1 for a key that is not set
    *) return 1 ;;
  esac
}
