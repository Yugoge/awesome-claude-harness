#!/usr/bin/env bash
# Unit test for AC1 V5: hooks/push.sh self-aborts before any real git push
# when the Chain-B sentinel is missing, expired (mtime > 60s), or FAIL-state.
#
# Strategy: mock the `git` binary via a temporary PATH shim that increments
# an invocation counter for every `git push` subcommand. Construct five
# fixtures (missing / expired / FAIL sentinel, plus the CF-3 missing-field
# and head-mismatch sentinels) and assert:
#   (a) hooks/push.sh exits non-zero on each fixture
#   (b) mocked-git push-invocation count is exactly zero on each fixture
#   (c) push.sh's refusal names that fixture's own reason
#
# This proves the sentinel-binding + mock-invocation-count-zero invariants
# from AC1 V5 of docs/dev/ticket-20260519-211515.md.
#
# Usage: bash hooks/tests/test_push_sentinel_abort.sh
# Exit:  0 = all 5 fixtures pass; 1 = any fixture failed.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PUSH_SH="${REPO_ROOT}/hooks/push.sh"
if [ ! -f "$PUSH_SH" ]; then
  echo "FAIL: cannot find $PUSH_SH" >&2
  exit 1
fi

WORKDIR=$(mktemp -d -t push-sentinel-test-XXXXXX)
trap 'rm -rf "$WORKDIR" 2>/dev/null' EXIT INT TERM

# push.sh reads the sentinel under $(harness_state_dir). Pin the state root to
# this run's scratch dir and write the fixtures through the same resolver, so
# an inherited CLAUDE_STATE_DIR can neither move push.sh's read away from the
# fixtures nor make this test write into the shared default /tmp root.
# shellcheck source=../lib/harness_state_dir.sh
. "${REPO_ROOT}/hooks/lib/harness_state_dir.sh"
export CLAUDE_STATE_DIR="$WORKDIR/state"

# ── Build a mock-git shim ────────────────────────────────────────────────
MOCK_BIN="$WORKDIR/bin"
mkdir -p "$MOCK_BIN"
INVOCATION_COUNT_FILE="$WORKDIR/mock-git-push-invocation-count"
echo 0 > "$INVOCATION_COUNT_FILE"

cat > "$MOCK_BIN/git" <<MOCK_GIT_EOF
#!/usr/bin/env bash
# Mocked git used by test_push_sentinel_abort.sh. Reads the same shim path
# from \$INVOCATION_COUNT_FILE to atomically increment the counter on any
# 'git push' subcommand invocation. All other subcommands are delegated
# to the real git via \$REAL_GIT for repo discovery / rev-parse calls used
# by hooks/push.sh before the sentinel gate.
case "\$1" in
  push)
    n=\$(cat "\$INVOCATION_COUNT_FILE" 2>/dev/null || echo 0)
    echo \$((n + 1)) > "\$INVOCATION_COUNT_FILE"
    echo "MOCK GIT PUSH (would have invoked: \$*)" >&2
    exit 99
    ;;
  rev-parse|status|remote|diff|branch|log|ls-files|rev-list|config)
    exec "\$REAL_GIT" "\$@"
    ;;
  *)
    exec "\$REAL_GIT" "\$@"
    ;;
esac
MOCK_GIT_EOF
chmod +x "$MOCK_BIN/git"

REAL_GIT=$(command -v git)
export REAL_GIT INVOCATION_COUNT_FILE

# Helper: write a Chain-B sentinel with controlled content + mtime.
# Note: head bound to "deadbeef" deliberately mismatches git HEAD so we test
# the head_mismatch branch with the PASS sentinel later; the three core
# fixtures (missing / expired / FAIL) do not reach the binding check.
_write_sentinel() {
  local result="$1" ; local age_seconds="${2:-0}" ; local body_kind="${3:-full}"
  local repo_hash
  repo_hash=$(python3 -c "import hashlib,os; print(hashlib.sha256(os.path.realpath('${REPO_ROOT}').encode()).hexdigest()[:16])")
  local branch_raw
  branch_raw=$("$REAL_GIT" -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)
  local branch
  branch=$(python3 -c "print('${branch_raw}'.replace('/', '__'))")
  local sdir
  sdir="$(harness_state_dir)/agentic-commit/push-analyst/${repo_hash}"
  mkdir -p "$sdir"
  local spath="${sdir}/${branch}-chainB.validated.sentinel.json"
  if [ "$body_kind" = "missing_fields" ]; then
    # CF-3 regression: result-only sentinel must NOT pass.
    printf '{"result":"%s"}' "$result" > "$spath"
  else
    BRANCH_RAW="$branch_raw" RESULT_VAL="$result" SPATH="$spath" python3 -c "
import json, os
json.dump({'result':os.environ['RESULT_VAL'],'request_id':'unit-test-req','head':'deadbeef','branch':os.environ['BRANCH_RAW'],'remote':'origin'}, open(os.environ['SPATH'],'w'))
"
  fi
  if [ "$age_seconds" -gt 0 ]; then
    # Backdate the mtime to make the sentinel stale.
    touch -d "@$(($(date -u +%s) - age_seconds))" "$spath"
  fi
  echo "$spath"
}

_reset_counter() {
  echo 0 > "$INVOCATION_COUNT_FILE"
}

_assert_zero_push_invocations() {
  local label="$1"
  local n
  n=$(cat "$INVOCATION_COUNT_FILE" 2>/dev/null || echo -1)
  if [ "$n" != "0" ]; then
    echo "FAIL: $label — mock-git push invocation count is $n, expected zero" >&2
    return 1
  fi
  echo "OK: $label — mock-git invocation count zero"
  return 0
}

# Each fixture must be refused for its own reason; a refusal for another
# reason (for example a sentinel looked up elsewhere) tests nothing.
_assert_reason() {
  local label="$1" out="$2" want="$3"
  if grep -qF -- "$want" "$out"; then
    echo "OK: $label — refused with '$want'"
    return 0
  fi
  echo "FAIL: $label — expected refusal reason '$want', got: $(head -c 300 "$out")" >&2
  return 1
}

FAILS=0

# ── Fixture 1: missing sentinel ──
_reset_counter
SENT_PATH=$(_write_sentinel PASS 0)
rm -f "$SENT_PATH"  # explicitly remove so sentinel is missing
set +e
PATH="$MOCK_BIN:$PATH" CLAUDE_PUSH_REQUEST_ID=unit-test-req bash "$PUSH_SH" origin --auto >"$WORKDIR/out1" 2>&1
status1=$?
set -e
if [ "$status1" -eq 0 ]; then
  echo "FAIL: fixture 1 (missing sentinel) — push.sh exited 0, expected non-zero" >&2
  FAILS=$((FAILS+1))
fi
_assert_zero_push_invocations "fixture 1 (missing sentinel)" || FAILS=$((FAILS+1))
_assert_reason "fixture 1 (missing sentinel)" "$WORKDIR/out1" "Chain-B sentinel missing" || FAILS=$((FAILS+1))

# ── Fixture 2: expired sentinel (mtime backdated 120s) ──
_reset_counter
SENT_PATH=$(_write_sentinel PASS 120)
set +e
PATH="$MOCK_BIN:$PATH" CLAUDE_PUSH_REQUEST_ID=unit-test-req bash "$PUSH_SH" origin --auto >"$WORKDIR/out2" 2>&1
status2=$?
set -e
if [ "$status2" -eq 0 ]; then
  echo "FAIL: fixture 2 (expired sentinel) — push.sh exited 0, expected non-zero" >&2
  FAILS=$((FAILS+1))
fi
_assert_zero_push_invocations "fixture 2 (expired sentinel)" || FAILS=$((FAILS+1))
_assert_reason "fixture 2 (expired sentinel)" "$WORKDIR/out2" "Chain-B sentinel STALE" || FAILS=$((FAILS+1))
rm -f "$SENT_PATH" 2>/dev/null

# ── Fixture 3: FAIL sentinel ──
_reset_counter
SENT_PATH=$(_write_sentinel FAIL 0)
set +e
PATH="$MOCK_BIN:$PATH" CLAUDE_PUSH_REQUEST_ID=unit-test-req bash "$PUSH_SH" origin --auto >"$WORKDIR/out3" 2>&1
status3=$?
set -e
if [ "$status3" -eq 0 ]; then
  echo "FAIL: fixture 3 (FAIL sentinel) — push.sh exited 0, expected non-zero" >&2
  FAILS=$((FAILS+1))
fi
_assert_zero_push_invocations "fixture 3 (FAIL sentinel)" || FAILS=$((FAILS+1))
_assert_reason "fixture 3 (FAIL sentinel)" "$WORKDIR/out3" "Chain-B sentinel reports FAIL" || FAILS=$((FAILS+1))
rm -f "$SENT_PATH" 2>/dev/null

# ── Fixture 4 (CF-3 regression): PASS sentinel with missing binding fields ──
_reset_counter
SENT_PATH=$(_write_sentinel PASS 0 missing_fields)
set +e
PATH="$MOCK_BIN:$PATH" CLAUDE_PUSH_REQUEST_ID=unit-test-req bash "$PUSH_SH" origin --auto >"$WORKDIR/out4" 2>&1
status4=$?
set -e
if [ "$status4" -eq 0 ]; then
  echo "FAIL: fixture 4 (PASS sentinel missing binding fields) — push.sh exited 0; CF-3 not fixed" >&2
  FAILS=$((FAILS+1))
fi
_assert_zero_push_invocations "fixture 4 (missing binding fields)" || FAILS=$((FAILS+1))
_assert_reason "fixture 4 (missing binding fields)" "$WORKDIR/out4" "missing required binding field" || FAILS=$((FAILS+1))
rm -f "$SENT_PATH" 2>/dev/null

# ── Fixture 5 (CF-3 regression): PASS sentinel with bound head mismatch ──
_reset_counter
SENT_PATH=$(_write_sentinel PASS 0 full)  # head=deadbeef intentionally != real HEAD
set +e
PATH="$MOCK_BIN:$PATH" CLAUDE_PUSH_REQUEST_ID=unit-test-req bash "$PUSH_SH" origin --auto >"$WORKDIR/out5" 2>&1
status5=$?
set -e
if [ "$status5" -eq 0 ]; then
  echo "FAIL: fixture 5 (head mismatch) — push.sh exited 0; CF-3 binding-mismatch not enforced" >&2
  FAILS=$((FAILS+1))
fi
_assert_zero_push_invocations "fixture 5 (head mismatch)" || FAILS=$((FAILS+1))
_assert_reason "fixture 5 (head mismatch)" "$WORKDIR/out5" "binding mismatch: head_mismatch" || FAILS=$((FAILS+1))
rm -f "$SENT_PATH" 2>/dev/null

if [ "$FAILS" -eq 0 ]; then
  echo "ALL 5 FIXTURES PASS: missing/expired/FAIL sentinel + CF-3 missing-fields + CF-3 head-mismatch — mock git invocation count zero in each"
  exit 0
else
  echo "$FAILS fixture(s) failed" >&2
  exit 1
fi
