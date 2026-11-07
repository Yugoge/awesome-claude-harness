#!/usr/bin/env bash
# Checks stop-spec-coverage-enforce.py, an exit-0 stub: G2 checks the split at the spec subagent's stop.
# Its rule (spec-verify.py on the /spec split) moved into the spec subagent's dispatch
# obligation, which hooks/subagentstop-artifact-contract-enforce.py checks at that
# subagent's own stop (P1b row 8; hooks/tests/test_g2_spec_views.py). The Stop
# coordinator still runs this file as its coverage phase, so it stays at its path and
# allows every Stop: here on a /spec session whose split is under-covered, the case the
# hook blocked before, and on an empty payload.
#
# Exit 0 = all checks passed, non-zero = failure count.

set -uo pipefail

HOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/hooks/stop-spec-coverage-enforce.py"
WORK="$(mktemp -d -t stop-spec-qa-XXXXXX)"
trap 'rm -rf "$WORK" 2>/dev/null' EXIT
export CLAUDE_PROJECT_DIR="$WORK"
mkdir -p "$WORK/docs/dev/specs/spec-20260423-080000/views" "$WORK/.claude/projects/-root"
printf '# Fake monolith\nContent that does not appear in views.\n' > "$WORK/docs/dev/specs/spec-20260423-080000.md"
printf '# Unrelated view content\n' > "$WORK/docs/dev/specs/spec-20260423-080000/views/ba.md"
TS="$WORK/.claude/projects/-root/session.jsonl"
cat > "$TS" <<JSONL
{"type": "user", "message": {"role": "user", "content": "/spec"}}
{"message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Write", "input": {"file_path": "$WORK/docs/dev/specs/spec-20260423-080000.md", "content": "stuff"}}]}}
{"message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "done"}]}}
JSONL

FAIL=0
check() {  # <name> <stdin>
  local out rc
  out="$(printf '%s' "$2" | python3 "$HOOK" 2>&1)"; rc=$?
  if [[ "$rc" == "0" && -z "$out" ]]; then echo "PASS: $1"; else echo "FAIL: $1 -- rc=$rc out=$out"; FAIL=$((FAIL+1)); fi
}
if grep -q '^# STUB:' "$HOOK"; then echo "PASS: stub_line"; else echo "FAIL: stub_line"; FAIL=$((FAIL+1)); fi
check under_covered_spec_stop "{\"session_id\":\"s\",\"transcript_path\":\"$TS\",\"stop_hook_active\":false}"
check empty_payload ""
exit "$FAIL"
