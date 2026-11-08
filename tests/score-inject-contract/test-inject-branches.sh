#!/usr/bin/env bash
# Description: Verify scripts/score-inject.sh emits INJECTION_PROOF block with
#   all 4 fields + correct sha256[:8] digest for populated and missing branches,
#   and exits 1 with stderr for malformed JSONL branch.
# Usage: test-inject-branches.sh [--score-inject <path>]
# Exit codes: 0=pass, 1=fail
#
# AC reference: docs/dev/acceptance-criteria-20260524-205206.json AC-02 (M2.3).
# Updated: arch-7 phase 2 (task 20260525-050824) — fixtures converted from JSON
# to JSONL format; malformed branch now expects exit code 1 + stderr (not INJECTION_PROOF).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCORE_INJECT_DEFAULT="$(cd "$SCRIPT_DIR/../.." && pwd)/scripts/score-inject.sh"
SCORE_INJECT="${1:-$SCORE_INJECT_DEFAULT}"

if [[ ! -x "$SCORE_INJECT" && ! -r "$SCORE_INJECT" ]]; then
  echo "FAIL: score-inject.sh not found at $SCORE_INJECT" >&2
  exit 1
fi

WORK_DIR="$(mktemp -d -t score-inject-test-XXXXXX)"
# Install cleanup trap BEFORE spawning any child processes
trap 'rm -rf "$WORK_DIR"' EXIT INT TERM

POPULATED="$WORK_DIR/populated.jsonl"
MISSING="$WORK_DIR/missing.jsonl"   # intentionally not created
MALFORMED="$WORK_DIR/malformed.jsonl"

# JSONL fixture: 3 score_update events for agent dev (score 55 after all events)
cat > "$POPULATED" <<'EOF'
{"ts":"2026-05-20T10:00:00Z","agent":"dev","event":"score_baseline_import","prev_score":50,"new_score":50,"delta":0,"unclamped_score":50,"actor":"migration","reason":"baseline import from agent-scores.json"}
{"ts":"2026-05-20T10:00:00Z","agent":"dev","event":"close_success_qa_pass","prev_score":50,"new_score":52,"delta":2,"unclamped_score":52,"actor":"orchestrator","reason":"test"}
{"ts":"2026-05-21T10:00:00Z","agent":"dev","event":"qa_first_pass","prev_score":52,"new_score":52,"delta":0,"unclamped_score":52,"actor":"orchestrator","reason":"test"}
{"ts":"2026-05-22T10:00:00Z","agent":"dev","event":"user_rating_5","prev_score":52,"new_score":53,"delta":1,"unclamped_score":53,"actor":"orchestrator","reason":"test"}
EOF

# MALFORMED: valid JSONL preamble followed by a non-JSON line (not the final line)
# so the malformed-non-final-line code path triggers exit 1 + stderr
cat > "$MALFORMED" <<'EOF'
{"ts":"2026-05-20T10:00:00Z","agent":"dev","event":"score_baseline_import","prev_score":50,"new_score":50,"delta":0,"unclamped_score":50,"actor":"migration","reason":"baseline import"}
{invalid: not, json,,
{"ts":"2026-05-21T10:00:00Z","agent":"dev","event":"close_success_qa_pass","prev_score":50,"new_score":52,"delta":2,"unclamped_score":52,"actor":"orchestrator","reason":"test"}
EOF

REQUIRED_TOKENS=(
  "INJECTION_PROOF:"
  "rank_acknowledged"
  "range_acknowledged"
  "recent_events_digest_acknowledged"
  "score_injection_action"
)

FORBIDDEN_PLACEHOLDERS=(
  "<RANK_LABEL>"
  "<RANGE>"
  "<RECENT_EVENTS_DIGEST>"
)

run_branch() {
  local label="$1"
  local lifecycle_path="$2"
  local out
  out="$(bash "$SCORE_INJECT" --agent dev --lifecycle-file "$lifecycle_path" 2>/dev/null)"

  # Check required tokens
  for tok in "${REQUIRED_TOKENS[@]}"; do
    if ! printf '%s' "$out" | grep -qF "$tok"; then
      echo "FAIL [$label]: missing required token: $tok" >&2
      echo "----- output -----" >&2
      printf '%s\n' "$out" >&2
      return 1
    fi
  done

  # Check unsubstituted placeholders absent for rank/range/digest
  # (score_injection_action <text> placeholder is fine — it's instructional)
  for ph in "${FORBIDDEN_PLACEHOLDERS[@]}"; do
    if printf '%s' "$out" | grep -F "$ph" | grep -qE '"(rank_acknowledged|range_acknowledged|recent_events_digest_acknowledged)":[[:space:]]*"[^"]*<'; then
      echo "FAIL [$label]: unsubstituted placeholder $ph found inside required field value" >&2
      return 1
    fi
  done

  # Extract the recent_events text from the "Recent events: <text>" line, and
  # the substituted digest from the INJECTION_PROOF line. Recompute sha256[:8]
  # over the recent_events text and assert equality.
  local recent_text emitted_digest expected_digest
  recent_text="$(printf '%s\n' "$out" | grep -oE 'Recent events:[[:space:]].*' | head -1 | sed -E 's/^Recent events:[[:space:]]//')"
  if [[ -z "$recent_text" ]]; then
    echo "FAIL [$label]: could not extract 'Recent events:' text from output" >&2
    return 1
  fi
  emitted_digest="$(printf '%s\n' "$out" | grep -oE '"recent_events_digest_acknowledged":[[:space:]]*"[0-9a-f]+"' | head -1 | sed -E 's/.*"([0-9a-f]+)".*/\1/')"
  if [[ -z "$emitted_digest" ]]; then
    echo "FAIL [$label]: could not extract recent_events_digest_acknowledged from output" >&2
    return 1
  fi
  if ! [[ "$emitted_digest" =~ ^[0-9a-f]{8}$ ]]; then
    echo "FAIL [$label]: digest is not 8 lowercase hex chars: '$emitted_digest'" >&2
    return 1
  fi
  expected_digest="$(printf '%s' "$recent_text" | sha256sum | cut -c1-8)"
  if [[ "$emitted_digest" != "$expected_digest" ]]; then
    echo "FAIL [$label]: digest mismatch — recent_events='$recent_text' expected=$expected_digest emitted=$emitted_digest" >&2
    return 1
  fi

  echo "PASS [$label]: all 4 fields present, digest recomputation OK ($emitted_digest)"
}

run_malformed_branch() {
  # Malformed JSONL must cause exit code 1 with stderr (not INJECTION_PROOF emission).
  local label="malformed"
  local lifecycle_path="$MALFORMED"
  local out stderr_out exit_code
  stderr_out="$(bash "$SCORE_INJECT" --agent dev --lifecycle-file "$lifecycle_path" 2>&1 >/dev/null)" || exit_code=$?
  out="$(bash "$SCORE_INJECT" --agent dev --lifecycle-file "$lifecycle_path" 2>/dev/null)" || true

  if [[ "${exit_code:-0}" -ne 1 ]]; then
    echo "FAIL [$label]: expected exit code 1 for malformed JSONL, got ${exit_code:-0}" >&2
    return 1
  fi
  if [[ -z "$stderr_out" ]]; then
    echo "FAIL [$label]: expected non-empty stderr for malformed JSONL" >&2
    return 1
  fi
  if printf '%s' "$out" | grep -qF "INJECTION_PROOF"; then
    echo "FAIL [$label]: stdout must NOT contain INJECTION_PROOF for malformed JSONL" >&2
    return 1
  fi
  echo "PASS [$label]: exit code 1, non-empty stderr, no INJECTION_PROOF in stdout"
}

ec=0
run_branch "populated" "$POPULATED" || ec=1
run_branch "missing"   "$MISSING"   || ec=1
run_malformed_branch || ec=1

if [[ $ec -ne 0 ]]; then
  echo "test-inject-branches.sh: at least one branch failed" >&2
  exit 1
fi
echo "test-inject-branches.sh: all 3 branches PASSED"
exit 0
