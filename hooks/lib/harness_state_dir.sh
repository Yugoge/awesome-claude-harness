#!/usr/bin/env bash
# harness_state_dir.sh -- shell twin of hooks/lib/harness_state_dir.py.
#
# Source it, then call:  STATE_DIR="$(harness_state_dir)"
# CLAUDE_STATE_DIR set to an absolute path -> that path (trailing slashes
# stripped); unset, empty or relative -> the historical default root.
# Not keyed on TMPDIR (per-session scratch): writer and reader hooks must agree.

harness_state_dir() {
  local v="${CLAUDE_STATE_DIR:-}"
  case "$v" in
    /*)
      while [ "${#v}" -gt 1 ] && [ "${v%/}" != "$v" ]; do v="${v%/}"; done
      printf '%s\n' "$v"
      ;;
    *)
      printf '%s\n' "/tmp"
      ;;
  esac
}
