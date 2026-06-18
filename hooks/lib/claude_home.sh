#!/usr/bin/env bash
# claude_home.sh — shared "harness home" resolver (shell consumable).
#
# Generalizes the in-repo gold-standard fail-closed self-resolution pattern
# (pretool-bash-safety.sh:8,83-106): resolve the harness root from the running
# file's OWN location, walking up to a STRUCTURAL sentinel SET, never to a
# directory literally named ".claude" (the author's RAM-disk root is named
# "dot-claude").
#
# Sentinel set (all four must be present together in the SAME directory):
#     settings.json  +  hooks/  +  policies/  +  scripts/
#
# Env hints (CLAUDE_HOME / HOME) are honored ONLY when their realpath equals the
# script-walk root — a fragile/empty/wrong $HOME never overrides the structural
# walk, which is PRIMARY.
#
# This file MUST be sourced, not executed directly:
#     source "$(dirname "${BASH_SOURCE[0]}")/lib/claude_home.sh"
#     CLAUDE_HOME="$(claude_home_resolve)"            # may be empty if unresolved
#     helper="$(require_security_file scripts/x.py)" || exit 2   # FAIL CLOSED
#     opt="$(resolve_optional_file scripts/y.py)"     # empty + nonzero if absent
#
# Public functions:
#   claude_home_resolve            -> prints resolved harness home, exit 0;
#                                     prints nothing + exit 1 if unresolved.
#   require_security_file <relpath> -> prints absolute path + exit 0 if present;
#                                     prints a block reason to stderr + exit 2 if
#                                     the home is unresolved OR the file is absent.
#                                     NEVER exit 1/127 — a missing REQUIRED
#                                     security helper/policy must BLOCK (exit 2).
#   resolve_optional_file <relpath> -> prints absolute path + exit 0 if present;
#                                     prints nothing + exit 1 (absent sentinel)
#                                     so the caller can degrade gracefully.

# ── Structural sentinel check ────────────────────────────────────────────────
# A directory is the harness home iff it contains ALL of: settings.json (file),
# hooks/ scripts/ policies/ (dirs). NEVER keyed on basename ".claude".
_claude_home_is_sentinel() {
  local d="$1"
  [ -f "$d/settings.json" ] && [ -d "$d/hooks" ] \
    && [ -d "$d/policies" ] && [ -d "$d/scripts" ]
}

# Walk upward from a starting directory to the first sentinel-matching ancestor.
# Prints the matching directory + returns 0, or returns 1 if none found.
_claude_home_walk_up() {
  local d="$1"
  d="$(cd "$d" 2>/dev/null && pwd -P)" || return 1
  while [ -n "$d" ]; do
    if _claude_home_is_sentinel "$d"; then
      printf '%s\n' "$d"
      return 0
    fi
    [ "$d" = "/" ] && break
    d="$(dirname "$d")"
  done
  return 1
}

# Realpath helper (portable; falls back to a Python one-liner if realpath absent).
_claude_home_realpath() {
  local p="$1"
  if command -v realpath >/dev/null 2>&1; then
    realpath "$p" 2>/dev/null && return 0
  fi
  local py="${CLAUDE_PYTHON_BIN:-python3}"
  "$py" -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$p" 2>/dev/null
}

# claude_home_resolve — PRIMARY: structural walk from this file's own location.
# Env hint (CLAUDE_HOME then HOME/.claude) is consulted only as a validated
# alternative AND only when its realpath equals the script-walk root.
claude_home_resolve() {
  local self_dir walk_root hint hint_real walk_real
  self_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)" || self_dir=""

  # script-walk root (PRIMARY): this file lives in <home>/hooks/lib/.
  walk_root=""
  if [ -n "$self_dir" ]; then
    walk_root="$(_claude_home_walk_up "$self_dir")" || walk_root=""
  fi

  # If a validated env hint realpath-equals the walk root, honor it (it may be
  # the user-facing symlinked form, e.g. ~/.claude -> the real tmpfs root).
  if [ -n "$walk_root" ]; then
    walk_real="$(_claude_home_realpath "$walk_root")"
    for hint in "${CLAUDE_HOME:-}" "${HOME:+${HOME}/.claude}"; do
      [ -n "$hint" ] || continue
      _claude_home_is_sentinel "$hint" || continue
      hint_real="$(_claude_home_realpath "$hint")"
      if [ -n "$hint_real" ] && [ "$hint_real" = "$walk_real" ]; then
        printf '%s\n' "$hint"
        return 0
      fi
    done
    printf '%s\n' "$walk_root"
    return 0
  fi

  # No script-walk root (e.g. resolver copied out of tree): accept an env hint
  # only if it is itself a structural sentinel. Never fabricate a /root default.
  for hint in "${CLAUDE_HOME:-}" "${HOME:+${HOME}/.claude}"; do
    [ -n "$hint" ] || continue
    if _claude_home_is_sentinel "$hint"; then
      printf '%s\n' "$hint"
      return 0
    fi
  done
  return 1
}

# require_security_file <relpath> — FAIL CLOSED.
# Prints the absolute path to <home>/<relpath> and exits 0 iff the harness home
# resolves AND the file exists. Otherwise prints a block reason to stderr and
# returns 2 — a security-relevant caller MUST `|| exit 2` so a missing REQUIRED
# helper/policy BLOCKS rather than silently continuing. Never returns 1/127.
require_security_file() {
  local relpath="$1" home abs
  if [ -z "$relpath" ]; then
    echo "claude_home: require_security_file needs a relative path" >&2
    return 2
  fi
  home="$(claude_home_resolve)"
  if [ -z "$home" ]; then
    echo "BLOCKED: claude_home FAIL-CLOSED — cannot resolve the harness home (no structural sentinel set: settings.json + hooks/ + policies/ + scripts/) from this hook's location; required security file '$relpath' is unreachable. Repair the harness install (run scripts/bootstrap)." >&2
    return 2
  fi
  abs="$home/$relpath"
  if [ ! -e "$abs" ]; then
    echo "BLOCKED: claude_home FAIL-CLOSED — required security file '$relpath' is absent under the resolved harness home '$home'. Denied conservatively; repair the harness install." >&2
    return 2
  fi
  printf '%s\n' "$abs"
  return 0
}

# resolve_optional_file <relpath> — graceful degradation.
# Prints the absolute path + exit 0 if present; prints NOTHING and returns 1
# (the "absent" sentinel) so the caller can branch and degrade. Never exit 2.
resolve_optional_file() {
  local relpath="$1" home abs
  [ -n "$relpath" ] || return 1
  home="$(claude_home_resolve)" || return 1
  [ -n "$home" ] || return 1
  abs="$home/$relpath"
  if [ -e "$abs" ]; then
    printf '%s\n' "$abs"
    return 0
  fi
  return 1
}

# When executed directly (not sourced), act as a tiny CLI so other languages /
# tests can shell out:  claude_home.sh resolve | require <rel> | optional <rel>
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  _cmd="${1:-resolve}"
  case "$_cmd" in
    resolve)
      claude_home_resolve || exit 1
      ;;
    require)
      require_security_file "${2:-}" || exit $?
      ;;
    optional)
      resolve_optional_file "${2:-}" || exit 1
      ;;
    *)
      echo "claude_home.sh: unknown subcommand '$_cmd' (resolve|require|optional)" >&2
      exit 2
      ;;
  esac
fi
