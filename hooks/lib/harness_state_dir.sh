#!/usr/bin/env bash
# harness_state_dir.sh -- shell twin of hooks/lib/harness_state_dir.py.
#
# Source it, then call:  STATE_DIR="$(harness_state_dir)"   ROOT="$(harness_state_root)"
# The same rule (trailing slashes stripped); the default directory is made when missing. Nothing here moves
# what an earlier version left in /tmp (scripts/install/carry_state.py is the explicit step).
_HSD_LIB="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")"
_HSD_LIB="$(cd -P "${_HSD_LIB%/*}" 2>/dev/null && pwd)"

harness_state_root() {
  local LC_ALL=C home="${_HSD_LIB%/*/*}" h=~ crc=4294967295 i j c n
  case "$h" in /*) ;; *) h="$(unset HOME; printf '%s' ~)" ;; esac
  n="${home##*/}"; while [ "${n#.}" != "$n" ]; do n="${n#.}"; done
  for ((i = 0; i < ${#home}; i++)); do
    printf -v c '%d' "'${home:i:1}"
    crc=$((crc ^ (c & 255)))
    for ((j = 0; j < 8; j++)); do crc=$(((crc >> 1) ^ (3988292384 & -(crc & 1)))); done
  done
  printf '%s/.local/state/claude-harness/%s-%08x\n' "$h" "$n" $((crc ^ 4294967295))
}

harness_state_dir() {
  local v="${CLAUDE_STATE_DIR:-}"
  case "$v" in
    /*)
      while [ "${#v}" -gt 1 ] && [ "${v%/}" != "$v" ]; do v="${v%/}"; done
      printf '%s\n' "$v"
      ;;
    *)
      v="$(harness_state_root)/state"
      [ -d "$v" ] || mkdir -p -m 700 "$v" 2>/dev/null
      printf '%s\n' "$v"
      ;;
  esac
}
