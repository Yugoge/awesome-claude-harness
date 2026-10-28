#!/usr/bin/env bash
# Description: Verify CAS and append-only invariants for scripts/score-update.sh and
#              the lifecycle read of scripts/score-inject.sh against a temporary lifecycle JSONL.
# Usage: test-lifecycle-cas.sh [--score-update <path>] [--score-inject <path>]
# Exit codes: 0=all pass, 1=at least one test failed
#
# Tests:
#   (a) successful append writes exactly one new JSONL line
#   (b) CAS conflict (wrong --expected-prev-score) exits 3 and appends zero lines
#   (c) append-only invariant: existing lines are byte-preserved after append
#   (e) score-inject.sh reads lifecycle.jsonl and ignores agent-scores.json after baseline import
#
# Root cause ref: arch-7 phase 2 (task 20260525-050824)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

SCORE_UPDATE="${SCORE_UPDATE:-$REPO_ROOT/scripts/score-update.sh}"
SCORE_INJECT="${SCORE_INJECT:-$REPO_ROOT/scripts/score-inject.sh}"

# Allow override via positional args for legacy compat
while [[ $# -gt 0 ]]; do
  case "$1" in
    --score-update)    SCORE_UPDATE="${2:?}"; shift 2 ;;
    --score-inject)    SCORE_INJECT="${2:?}"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

WORK_DIR="$(mktemp -d -t lifecycle-cas-test-XXXXXX)"
# Install cleanup trap BEFORE spawning any child processes
trap 'rm -rf "$WORK_DIR"' EXIT INT TERM

LIFECYCLE="$WORK_DIR/lifecycle.jsonl"
FAKE_SCORES="$WORK_DIR/agent-scores.json"

PASS_COUNT=0
FAIL_COUNT=0

assert_pass() {
  local label="$1"
  echo "PASS [$label]"
  ((PASS_COUNT++)) || true
}

assert_fail() {
  local label="$1"
  local msg="$2"
  echo "FAIL [$label]: $msg" >&2
  ((FAIL_COUNT++)) || true
}

line_count() {
  # Count non-empty lines in the lifecycle file
  if [[ ! -f "$LIFECYCLE" ]]; then echo 0; return; fi
  grep -c . "$LIFECYCLE" 2>/dev/null || echo 0
}

# Seed lifecycle with one entry for agent dev with new_score=50
seed_dev_score_50() {
  printf '{"ts":"2026-05-25T00:00:00Z","agent":"dev","event":"score_baseline_import","prev_score":50,"new_score":50,"delta":0,"unclamped_score":50,"actor":"migration","reason":"seed"}\n' > "$LIFECYCLE"
}

# ---------------------------------------------------------------
# Test (a): successful append writes exactly one new JSONL line
# ---------------------------------------------------------------
seed_dev_score_50
before_count=$(line_count)
bash "$SCORE_UPDATE" --agent dev --event close_success_qa_pass --note "cas-test-a" \
  --lifecycle-file "$LIFECYCLE" >/dev/null
after_count=$(line_count)

if [[ $((after_count - before_count)) -eq 1 ]]; then
  assert_pass "a: successful append adds exactly 1 line"
else
  assert_fail "a: successful append adds exactly 1 line" "before=$before_count after=$after_count (expected diff=1)"
fi

# Verify new line is valid JSON with all 9 mandatory fields
last_line="$(tail -1 "$LIFECYCLE")"
if source ~/.claude/venv/bin/activate && python3 - "$last_line" <<'PYCHECK'
import json, sys
line = sys.argv[1]
entry = json.loads(line)
required = {"ts","agent","event","prev_score","new_score","delta","unclamped_score","actor","reason"}
missing = required - set(entry.keys())
forbidden = {"note", "uncapped_delta"}
present_forbidden = forbidden & set(entry.keys())
if missing:
    sys.stderr.write(f"missing fields: {missing}\n"); sys.exit(1)
if present_forbidden:
    sys.stderr.write(f"forbidden fields present: {present_forbidden}\n"); sys.exit(1)
if entry.get("reason") is None:
    sys.stderr.write("reason field is None\n"); sys.exit(1)
if entry["unclamped_score"] != entry["prev_score"] + entry["delta"]:
    sys.stderr.write(f"unclamped_score={entry['unclamped_score']} != prev_score+delta={entry['prev_score']+entry['delta']}\n"); sys.exit(1)
PYCHECK
then
  assert_pass "a: new line has all 9 mandatory fields, no forbidden fields, unclamped_score correct"
else
  assert_fail "a: new line has all 9 mandatory fields, no forbidden fields, unclamped_score correct" "field check failed — see stderr"
fi

# ---------------------------------------------------------------
# Test (b): CAS conflict exits 3 and appends zero lines
# ---------------------------------------------------------------
seed_dev_score_50
before_count=$(line_count)
exit_code=0
bash "$SCORE_UPDATE" --agent dev --event close_success_qa_pass \
  --expected-prev-score 99 \
  --lifecycle-file "$LIFECYCLE" >/dev/null 2>/dev/null || exit_code=$?
after_count=$(line_count)

if [[ $exit_code -eq 3 ]]; then
  assert_pass "b: CAS conflict exits 3"
else
  assert_fail "b: CAS conflict exits 3" "got exit code $exit_code"
fi

if [[ $((after_count - before_count)) -eq 0 ]]; then
  assert_pass "b: CAS conflict appends zero lines"
else
  assert_fail "b: CAS conflict appends zero lines" "before=$before_count after=$after_count (expected diff=0)"
fi

# ---------------------------------------------------------------
# Test (c): append-only invariant — existing lines byte-preserved
# ---------------------------------------------------------------
seed_dev_score_50
original_content="$(cat "$LIFECYCLE")"
bash "$SCORE_UPDATE" --agent dev --event close_success_qa_pass --note "preserve-test" \
  --lifecycle-file "$LIFECYCLE" >/dev/null
new_content="$(cat "$LIFECYCLE")"

if [[ "$new_content" == "${original_content}"* ]]; then
  assert_pass "c: existing lines byte-preserved after append"
else
  assert_fail "c: existing lines byte-preserved after append" "original content is not a prefix of new content"
fi

# ---------------------------------------------------------------
# Test (e): score-inject reads lifecycle.jsonl; ignores agent-scores.json
# ---------------------------------------------------------------
# Seed lifecycle with ba at score 70 (Senior Craftsman range 61-80)
rm -f "$LIFECYCLE" && touch "$LIFECYCLE"
printf '{"ts":"2026-05-25T00:00:00Z","agent":"ba","event":"score_baseline_import","prev_score":70,"new_score":70,"delta":0,"unclamped_score":70,"actor":"migration","reason":"seed"}\n' > "$LIFECYCLE"

# Create fake agent-scores.json with ba at score 40 (Journeyman range 21-40)
( source ~/.claude/venv/bin/activate && python3 - "$FAKE_SCORES" <<'PYEOF'
import json, sys
data = {"global":{"agents":{"ba":{"score":40,"rank":"Journeyman","history":[]}}}}
with open(sys.argv[1], "w") as f:
    json.dump(data, f)
PYEOF
)

# Run score-inject with --lifecycle-file pointing to our temp file
inject_out="$(bash "$SCORE_INJECT" --agent ba --lifecycle-file "$LIFECYCLE" 2>/dev/null)"

if printf '%s' "$inject_out" | grep -qF "[Range: 61-80]"; then
  assert_pass "e: score-inject reads lifecycle.jsonl (range 61-80 for score 70)"
else
  assert_fail "e: score-inject reads lifecycle.jsonl" "output does not contain [Range: 61-80]: $inject_out"
fi

if ! printf '%s' "$inject_out" | grep -qF "[Range: 21-40]"; then
  assert_pass "e: score-inject does not use agent-scores.json range (21-40 absent)"
else
  assert_fail "e: score-inject does not use agent-scores.json range" "output contains wrong range [Range: 21-40]"
fi

# ---------------------------------------------------------------
# Summary
# ---------------------------------------------------------------
echo ""
echo "test-lifecycle-cas.sh: PASS=$PASS_COUNT FAIL=$FAIL_COUNT"
if [[ $FAIL_COUNT -gt 0 ]]; then
  exit 1
fi
exit 0
