#!/usr/bin/env bash
# refusal_record.sh -- a shell hook's report to the refusal record (hooks/lib/refusal_record.py).
#
# Source it once the hook has read its input into INPUT, then:  trap refusal_record_on_exit EXIT
# When the hook exits 2, whichever line refuses, the trap writes one line: the refusing file
# (_REFUSED_BY, default the hook itself) and the first line it printed (_SAID). The hook's exit
# status stays what it was; an exit other than 2 starts nothing.

refusal_record_on_exit() {
  [ $? -eq 2 ] || return 0
  printf '%s' "${INPUT:-}" | "${PYTHON_BIN:-python3}" "$(dirname "${BASH_SOURCE[0]}")/refusal_record.py" \
    "$0" "${_REFUSED_BY:-$0}" "${_SAID:-}" >/dev/null 2>&1
  return 0
}
