#!/usr/bin/env bash
# auto_push.sh -- harness_auto_push, the one reader of the per-repository push switch.
#
# Source it, then call:  harness_auto_push <repo-dir>   (exit 0 = push, anything else = no push)
# D1 as amended: the repository's LOCAL git config harness.autoPush decides first. A value git
# reads as true pushes; false, or a value git cannot read as a boolean, does not. Unset, the global
# GIT_AUTO_PUSH decides as before: exactly "1" pushes. A global or system harness.autoPush is not
# read, so the one global switch stays GIT_AUTO_PUSH. Every automatic push path calls this:
# _checkpoint_rate_limited_push (lib/checkpoint-core.sh), safe_push (git-fswatch.sh) and the
# initial push of session-git-init.sh.

harness_auto_push() {
  local v rc
  v="$(git -C "${1:-.}" config --local --type=bool --get harness.autoPush 2>/dev/null)"
  rc=$?
  case "$rc:$v" in
    0:true) return 0 ;;
    1:) [ "${GIT_AUTO_PUSH:-}" = "1" ] ;;  # git exits 1 for a key that is not set
    *) return 1 ;;
  esac
}
