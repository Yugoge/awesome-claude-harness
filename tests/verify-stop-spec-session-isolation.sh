#!/usr/bin/env bash
# QA verification harness for stop-spec-coverage-enforce.py session isolation fix.
# Covers AC1-AC5 + critical regression checks from dev-20260424-093644.
#
# Exit 0 = all tests passed, non-zero = failure count.

set -uo pipefail

# The hook under test is the one in this checkout (this script lives at <repo>/tests/).
HOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/hooks/stop-spec-coverage-enforce.py"
WORK="$(mktemp -d -t stop-spec-qa-XXXXXX)"
_cleanup_work() { rm -rf "$WORK" 2>/dev/null; }
trap '_cleanup_work' EXIT
trap '_cleanup_work; exit 130' INT
trap '_cleanup_work; exit 143' TERM
export CLAUDE_PROJECT_DIR="$WORK"
mkdir -p "$WORK/.claude"
mkdir -p "$WORK/docs/dev/specs/spec-20260423-080000/views"
mkdir -p "$WORK/docs/dev/specs/spec-20260424-090315-test"  # no views/ dir
# Put a monolith file for the views-present spec so spec-verify is reachable
cat > "$WORK/docs/dev/specs/spec-20260423-080000.md" <<'EOF'
# Fake monolith for spec-20260423-080000
Content that does not appear in views.
EOF
# And a view file (deliberately not matching monolith -> spec-verify should fail)
cat > "$WORK/docs/dev/specs/spec-20260423-080000/views/ba.md" <<'EOF'
# Unrelated view content
EOF
cat > "$WORK/docs/dev/specs/spec-20260424-090315-test.md" <<'EOF'
# Fake monolith for spec-20260424-090315-test (no views dir)
EOF

PASS=0
FAIL=0
declare -a FAILS

log_pass() { echo "PASS: $1"; PASS=$((PASS+1)); }
log_fail() { echo "FAIL: $1  -- $2"; FAIL=$((FAIL+1)); FAILS+=("$1"); }

make_bookmark() {
  local sid="$1" cmd="$2"
  cat > "$WORK/.claude/workflow-${sid}.json" <<EOF
{"command": "${cmd}", "todo_acknowledged": true, "last_todos": []}
EOF
}

make_transcript_with_spec() {
  local path="$1" file_path="$2" tool_name="${3:-Write}"
  cat > "$path" <<EOF
{"message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}
{"message": {"role": "user", "content": [{"type": "tool_result", "content": "done"}]}}
{"message": {"role": "assistant", "content": [{"type": "tool_use", "name": "${tool_name}", "input": {"file_path": "${file_path}", "content": "stuff"}}]}}
EOF
}

make_transcript_empty() {
  local path="$1"
  cat > "$path" <<EOF
{"message": {"role": "assistant", "content": [{"type": "text", "text": "hello"}]}}
{"message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}}
EOF
}

run_hook() {
  local stdin_json="$1"
  echo "$stdin_json" | python3 "$HOOK" >/dev/null 2>"$WORK/stderr.log"
  echo $?
}

# ==================================================================
# Test 1: Cross-session isolation (the original bug)
# ==================================================================

SID_A="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SID_B="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
make_bookmark "$SID_A" "spec"
make_bookmark "$SID_B" "spec"

TSA="$WORK/.claude/projects/-root/${SID_A}.jsonl"
TSB="$WORK/.claude/projects/-root/${SID_B}.jsonl"
mkdir -p "$(dirname "$TSA")"
# Session A touched spec-20260424-090315-test (no views/ dir)
make_transcript_with_spec "$TSA" "/root/docs/dev/specs/spec-20260424-090315-test.md"
# Session B touched spec-20260423-080000 (has views/ dir, will fail coverage)
make_transcript_with_spec "$TSB" "/root/docs/dev/specs/spec-20260423-080000/views/ba.md"

# Session A stop: should exit 0 (no views/ for its spec) — NOT be blocked by B's spec
RC=$(run_hook "{\"session_id\":\"$SID_A\",\"transcript_path\":\"$TSA\",\"stop_hook_active\":false}")
if [[ "$RC" == "0" ]]; then
  log_pass "cross_session_isolation_A: session A with no-views spec exits 0 (not blocked by B)"
else
  log_fail "cross_session_isolation_A" "expected rc=0, got rc=$RC; stderr: $(cat "$WORK/stderr.log")"
fi

# Session B: must target spec-20260423-080000 (its own spec via transcript) — breadcrumb should say so
RC=$(run_hook "{\"session_id\":\"$SID_B\",\"transcript_path\":\"$TSB\",\"stop_hook_active\":false}")
STDERR_B="$(cat "$WORK/stderr.log")"
if grep -q "target spec: spec-20260423-080000" <<<"$STDERR_B"; then
  log_pass "cross_session_isolation_B: session B correctly derived spec-20260423-080000 from own transcript"
else
  log_fail "cross_session_isolation_B" "expected breadcrumb 'target spec: spec-20260423-080000'; got: $STDERR_B"
fi

# Critical: session A MUST NOT trigger coverage against spec-20260423-080000
STDERR_A_LOG="$WORK/stderr_a.log"
echo "{\"session_id\":\"$SID_A\",\"transcript_path\":\"$TSA\",\"stop_hook_active\":false}" | python3 "$HOOK" >/dev/null 2>"$STDERR_A_LOG"
if grep -q "spec-20260423-080000" "$STDERR_A_LOG"; then
  log_fail "cross_session_isolation_A_no_leak" "session A stderr mentions spec-20260423-080000 — leak: $(cat $STDERR_A_LOG)"
else
  log_pass "cross_session_isolation_A_no_leak: session A's stop did NOT reference spec-20260423-080000"
fi

# ==================================================================
# Test 2: No-spec-touched — hook exits 0
# ==================================================================
SID_C="cccccccc-cccc-cccc-cccc-cccccccccccc"
make_bookmark "$SID_C" "spec"
TSC="$WORK/.claude/projects/-root/${SID_C}.jsonl"
make_transcript_empty "$TSC"

RC=$(run_hook "{\"session_id\":\"$SID_C\",\"transcript_path\":\"$TSC\",\"stop_hook_active\":false}")
if [[ "$RC" == "0" ]]; then
  log_pass "no_spec_touched: rc=0"
else
  log_fail "no_spec_touched" "expected rc=0, got rc=$RC; stderr: $(cat "$WORK/stderr.log")"
fi

# ==================================================================
# Test 3: Transcript missing file
# ==================================================================
SID_D="dddddddd-dddd-dddd-dddd-dddddddddddd"
make_bookmark "$SID_D" "spec"
RC=$(run_hook "{\"session_id\":\"$SID_D\",\"transcript_path\":\"/nonexistent/path.jsonl\",\"stop_hook_active\":false}")
if [[ "$RC" == "0" ]]; then
  log_pass "transcript_missing: rc=0"
else
  log_fail "transcript_missing" "expected rc=0, got rc=$RC; stderr: $(cat "$WORK/stderr.log")"
fi

# ==================================================================
# Test 4: stop_hook_active re-entrance guard
# ==================================================================
# Should exit 0 regardless of other fields
RC=$(run_hook "{\"session_id\":\"$SID_B\",\"transcript_path\":\"$TSB\",\"stop_hook_active\":true}")
if [[ "$RC" == "0" ]]; then
  log_pass "stop_hook_active: re-entrance guard exits 0"
else
  log_fail "stop_hook_active" "expected rc=0 (guard), got rc=$RC; stderr: $(cat "$WORK/stderr.log")"
fi

# ==================================================================
# Test 5: Non-spec workflow — hook exits 0
# ==================================================================
SID_E="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
make_bookmark "$SID_E" "dev"  # not 'spec'
TSE="$WORK/.claude/projects/-root/${SID_E}.jsonl"
make_transcript_with_spec "$TSE" "/root/docs/dev/specs/spec-20260423-080000/views/ba.md"
RC=$(run_hook "{\"session_id\":\"$SID_E\",\"transcript_path\":\"$TSE\",\"stop_hook_active\":false}")
if [[ "$RC" == "0" ]]; then
  log_pass "non_spec_workflow: rc=0"
else
  log_fail "non_spec_workflow" "expected rc=0, got rc=$RC; stderr: $(cat "$WORK/stderr.log")"
fi

# ==================================================================
# Test 6 (bonus): transcript_path absent in stdin (AC5)
# ==================================================================
RC=$(run_hook "{\"session_id\":\"$SID_B\",\"stop_hook_active\":false}")
if [[ "$RC" == "0" ]]; then
  log_pass "transcript_path_absent: rc=0"
else
  log_fail "transcript_path_absent" "expected rc=0, got rc=$RC; stderr: $(cat "$WORK/stderr.log")"
fi

# ==================================================================
# Test 7 (bonus): Spec in transcript, views/ missing (AC4)
# ==================================================================
# Session A already tests this — assert specifically.
RC=$(run_hook "{\"session_id\":\"$SID_A\",\"transcript_path\":\"$TSA\",\"stop_hook_active\":false}")
if [[ "$RC" == "0" ]]; then
  log_pass "spec_touched_no_views_dir: rc=0"
else
  log_fail "spec_touched_no_views_dir" "expected rc=0, got rc=$RC"
fi

# ==================================================================
# Test 8 (bonus): corrupted/non-JSON line in transcript — should fallthrough None
# ==================================================================
SID_F="ffffffff-ffff-ffff-ffff-ffffffffffff"
make_bookmark "$SID_F" "spec"
TSF="$WORK/.claude/projects/-root/${SID_F}.jsonl"
cat > "$TSF" <<'EOF'
this is not json
{not valid either
{"message": {"role": "assistant", "content": "not a list"}}
EOF
RC=$(run_hook "{\"session_id\":\"$SID_F\",\"transcript_path\":\"$TSF\",\"stop_hook_active\":false}")
if [[ "$RC" == "0" ]]; then
  log_pass "corrupt_transcript_lines: rc=0 (exceptions contained)"
else
  log_fail "corrupt_transcript_lines" "expected rc=0, got rc=$RC"
fi

# ==================================================================
# Test 9 (bonus): 500-line cap sanity — transcript with 1000 lines,
# spec mention only in the last 10 lines, should still find it.
# ==================================================================
SID_G="99999999-9999-9999-9999-999999999999"
make_bookmark "$SID_G" "spec"
TSG="$WORK/.claude/projects/-root/${SID_G}.jsonl"
python3 - <<PYEOF
import json
with open("$TSG", "w") as f:
    for i in range(1000):
        f.write(json.dumps({"message":{"role":"user","content":[{"type":"text","text":f"line {i}"}]}}) + "\n")
    # last line: spec-touching tool_use
    f.write(json.dumps({"message":{"role":"assistant","content":[{"type":"tool_use","name":"Write","input":{"file_path":"/root/docs/dev/specs/spec-20260423-080000/views/ba.md"}}]}}) + "\n")
PYEOF

RC=$(run_hook "{\"session_id\":\"$SID_G\",\"transcript_path\":\"$TSG\",\"stop_hook_active\":false}")
STDERR_G="$(cat "$WORK/stderr.log")"
if grep -q "target spec: spec-20260423-080000" <<<"$STDERR_G"; then
  log_pass "tail_cap_finds_recent_match: 500-line reverse scan reaches last-line spec ref"
else
  log_fail "tail_cap_finds_recent_match" "expected breadcrumb; got: $STDERR_G"
fi

# ==================================================================
# Test 10: Ordering-bug regression — Write(own) then Read(foreign)
# must target own-spec, not the more-recently-Read foreign spec.
# (Regression for commit ad9759c; see close-report-20260424-133333.md)
# ==================================================================
SID_H="11111111-1111-1111-1111-111111111111"
make_bookmark "$SID_H" "spec"
TSH="$WORK/.claude/projects/-root/${SID_H}.jsonl"
# Transcript order: Write(own-new-spec) first, then Read(foreign-spec views).
# Reverse scan must ignore the Read and return spec-20260424-111111.
# spec-20260424-111111 has no monolith and no views/ dir in $WORK,
# so AC3/AC4 applies: hook exits 0 even after correct targeting.
cat > "$TSH" <<'EOF'
{"message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Write", "input": {"file_path": "/root/docs/dev/specs/spec-20260424-111111.md", "content": "own spec"}}]}}
{"message": {"role": "user", "content": [{"type": "tool_result", "content": "done"}]}}
{"message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/root/docs/dev/specs/spec-20260423-080000/views/ba.md"}}]}}
EOF

RC=$(run_hook "{\"session_id\":\"$SID_H\",\"transcript_path\":\"$TSH\",\"stop_hook_active\":false}")
STDERR_H="$(cat "$WORK/stderr.log")"
if [[ "$RC" != "0" ]]; then
  log_fail "ordering_bug_write_then_read_foreign" "expected rc=0, got rc=$RC; stderr: $STDERR_H"
elif grep -q "spec-20260423-080000" <<<"$STDERR_H"; then
  log_fail "ordering_bug_write_then_read_foreign" "foreign spec leaked into stderr — Read overrode Write: $STDERR_H"
elif grep -q "⛔ SPEC COVERAGE ENFORCEMENT" <<<"$STDERR_H"; then
  log_fail "ordering_bug_write_then_read_foreign" "hook emitted blocking message when it should have exited 0: $STDERR_H"
else
  log_pass "ordering_bug_write_then_read_foreign: Read(foreign) ignored; Write(own) correctly drives target; rc=0"
fi

# ==================================================================
# Cleanup
# ==================================================================
rm -rf "$WORK"

echo ""
echo "============================================"
echo "Results: PASS=$PASS FAIL=$FAIL"
echo "============================================"
if (( FAIL > 0 )); then
  echo "Failed tests:"
  for f in "${FAILS[@]}"; do echo "  - $f"; done
  exit "$FAIL"
fi
exit 0
