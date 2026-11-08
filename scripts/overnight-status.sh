#!/bin/bash
# overnight-status.sh — Zero-LLM overnight session status query
# Reads the record through hooks/lib/overnight.py, the record's one reading and
# the one rule on its window, so it never decides "expired" by a rule of its own.
#
# Usage: bash ~/.claude/scripts/overnight-status.sh [state_file|session_id] [state_dir]
#   state_file  the record itself (.../.claude/overnight-state-<sid>.json)
#   session_id  <state_dir>/overnight-state-<session_id>.json
#   neither     the newest record in <state_dir>
# state_dir defaults to OVERNIGHT_STATE_DIR, else the .claude/ directory the
# launcher writes the record to ($CLAUDE_PROJECT_DIR, else the current directory).
#
# Exit: 0 while the session's window is open; 1 once it has closed or when no
# record is found. /dev-overnight Step 19's TIME CHECK routes on this status.

set -euo pipefail

LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../hooks/lib" && pwd)"
STATE_DIR="${2:-${OVERNIGHT_STATE_DIR:-${CLAUDE_PROJECT_DIR:-$PWD}/.claude}}"

if [ -n "${1:-}" ] && [ -f "$1" ]; then
    STATE="$1"
elif [ -n "${1:-}" ]; then
    STATE="$STATE_DIR/overnight-state-$1.json"
else
    STATE=$(find "$STATE_DIR" -maxdepth 1 -name "overnight-state-*.json" -printf '%T@ %p\n' 2>/dev/null \
        | sort -rn | head -1 | cut -d' ' -f2- || true)
fi

exec python3 -I - "$LIB_DIR" "${STATE:-}" <<'PY'
import sys
from datetime import datetime, timezone

sys.path.insert(0, sys.argv[1])
import overnight  # noqa: E402

record = overnight.read_state(sys.argv[2]) if sys.argv[2] else None
if record is None:
    print("No overnight session found.")
    sys.exit(1)
verdicts = overnight.state_verdicts(record)
if verdicts.window_live:
    end = verdicts.end_time
    now = datetime.now(timezone.utc) if end.tzinfo else datetime.now()
    minutes = max(0, int((end - now).total_seconds()) // 60)
    window = f"open, {minutes // 60}h {minutes % 60}m remaining"
else:
    window = "closed"


def count(field):
    value = record.get(field)
    return len(value) if isinstance(value, list) else 0


found = record.get("issues_found") or 0
fixed = record.get("issues_fixed") or 0
rule = "━" * 42
lines = [
    rule,
    "  Overnight Session Status",
    rule,
    f"  Session:  {record.get('session_id') or 'unknown'}",
    f"  Phase:    {record.get('current_phase') or 'unknown'}",
    f"  Cycle:    {overnight.cycle_index(record)}",
    f"  Window:   {window}",
    rule,
    f"  Issues found:   {found}",
    f"  Issues fixed:   {fixed}",
    f"  Issues skipped: {record.get('issues_skipped') or 0}",
    f"  Fix rate:       {int(fixed / found * 100)}%" if found else "  Fix rate:       N/A",
    rule,
    f"  Start:    {record.get('start_time') or 'unknown'}",
    f"  End:      {record.get('end_time') or 'unknown'}",
    f"  Clean sweeps: {record.get('consecutive_clean_sweeps') or 0}",
    rule,
    f"  Triage reports:  {count('pm_triage_reports')}",
    f"  Retro reports:   {count('pm_retro_reports')}",
    f"  Unresolved: {count('unresolved_issues')} issues",
]
for issue in record.get("unresolved_issues") or []:
    if isinstance(issue, dict):
        lines.append(f"    - [{issue.get('severity') or '?'}] {str(issue.get('description') or '?')[:60]}")
lines.append(rule)
print("\n".join(lines))
sys.exit(0 if verdicts.window_live else 1)
PY
