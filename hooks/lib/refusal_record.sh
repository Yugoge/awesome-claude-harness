#!/usr/bin/env bash
# refusal_record.sh -- a shell hook's report to the refusal record (hooks/lib/refusal_record.py).
#
# Source it once the hook has read its input into INPUT, then:  trap refusal_record_on_exit EXIT
# When the hook exits 2, whichever line refuses, the trap reports one refusal to the writer: the
# refusing file (_REFUSED_BY, default the hook itself) and the first line it printed (_SAID). The
# hook's exit status stays what it was; an exit other than 2, or an input that names no hook event
# (a canary's probe), starts nothing.

refusal_record_on_exit() {
  [ $? -eq 2 ] || return 0
  case "${INPUT:-}" in *'"hook_event_name"'*) ;; *) return 0 ;; esac
  printf '%s' "$INPUT" | "${PYTHON_BIN:-python3}" "$(dirname "${BASH_SOURCE[0]}")/refusal_record.py" \
    refusal "$0" "${_REFUSED_BY:-$0}" "${_SAID:-}" >/dev/null 2>&1
  return 0
}
