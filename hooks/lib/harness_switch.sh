#!/usr/bin/env bash
# harness_switch.sh — the harness switch's one question for shell hooks and jobs: is this
# harness home switched off (/harness off)? The same test as hooks/lib/harness_switch.py: the
# file <harness home>/.harness-switch/off, the home being two levels above this file (symlinks
# resolved). Source it, then:
#     harness_switch_off            # status 0 while the switch is off, 1 while it is on
#     harness_switch_exit_if_off    # exit 0, printing nothing, while the switch is off
# A hook sources it as its first command, before `set -e` and before it reads its input.
harness_switch_off() {
  local lib
  lib="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)" || return 1
  [ -e "${lib%/hooks/lib}/.harness-switch/off" ]
}
harness_switch_exit_if_off() {
  if harness_switch_off; then exit 0; fi
  return 0
}
