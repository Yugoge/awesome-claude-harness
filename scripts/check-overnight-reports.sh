#!/usr/bin/env bash
# Validates the reports a /dev-overnight cycle's dispatches declared in the
# session's report directory: check-overnight-reports.py reads each report's path
# and schema from the obligation its dispatch carried and checks the report
# against that schema. G2 (hooks/subagentstop-artifact-contract-enforce.py) checks
# the same reports at each producer's own stop once CLAUDE_OBLIGATION_STOPGATE
# blocks; until then this check is their stop.
#
# Callers may use the Python implementation directly:
#   check-overnight-reports.py --session-id <sid> [--cycle <N>]
#
# This shim accepts the positional <report_dir> argument the /dev-overnight text
# passes (docs/dev/overnight/<session_id>) and derives the session id from its
# name.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_SCRIPT="$SCRIPT_DIR/check-overnight-reports.py"

if [[ ! -f "$PY_SCRIPT" ]]; then
    echo "ERROR: $PY_SCRIPT missing — obligation-driven validator not installed" >&2
    exit 1
fi

# Activate venv if available
VENV_DIR="${SCRIPT_DIR}/../venv"
if [[ -f "${VENV_DIR}/bin/activate" ]]; then
    source "${VENV_DIR}/bin/activate"
elif [[ -f "${SCRIPT_DIR}/../.venv/bin/activate" ]]; then
    source "${SCRIPT_DIR}/../.venv/bin/activate"
fi

# Best-effort: if a single positional argument is supplied (legacy
# <report_dir>), try to derive a session id from the directory name. Any
# caller that needs full control should switch to the .py directly.
if [[ "$#" -eq 1 && -d "$1" ]]; then
    SESSION_ID="$(basename "$1")"
    exec python3 "$PY_SCRIPT" --session-id "$SESSION_ID"
fi

exec python3 "$PY_SCRIPT" "$@"
