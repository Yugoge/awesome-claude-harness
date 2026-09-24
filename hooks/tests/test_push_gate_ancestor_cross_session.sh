#!/usr/bin/env bash
# Regression test for hooks/push.sh's push-gate token scan (task 20260924-031253):
# the check widened from same-session + commit_sha==HEAD to cross-session +
# ancestor-of-HEAD. See commands/push.md "Session commit prerequisite (push-gate)"
# for the full rationale.
#
# This test extracts the REAL scanning block verbatim from the live
# hooks/push.sh (anchor + line-range, not a hand-copied duplicate) and evals
# it against fabricated scratch scenarios. If a future edit narrows the check
# back to strict equality or same-session-only, the extraction still picks up
# the regressed logic and the relevant assertion fails.
#
# Usage: bash hooks/tests/test_push_gate_ancestor_cross_session.sh
# Exit:  0 = all assertions pass; 1 = any assertion failed.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PUSH_SH="${REPO_ROOT}/hooks/push.sh"
if [ ! -f "$PUSH_SH" ]; then
  echo "FAIL: cannot find $PUSH_SH" >&2
  exit 1
fi

FAIL=0

# ── Extract the REAL scanning block verbatim from hooks/push.sh ───────────
START_ANCHOR='_TOKEN_BASE_DIR="/tmp/agentic-commit/push/${_REPO_HASH}"'
END_ANCHOR='if [ -z "$_TOKEN_PATH" ]; then'
START_LINE=$(grep -nF "$START_ANCHOR" "$PUSH_SH" | head -1 | cut -d: -f1)
END_LINE=$(grep -nF "$END_ANCHOR" "$PUSH_SH" | head -1 | cut -d: -f1)
if [ -z "$START_LINE" ] || [ -z "$END_LINE" ] || [ "$END_LINE" -le "$START_LINE" ]; then
  echo "FAIL: could not locate the push-gate scan block in $PUSH_SH (anchors not found or out of order -- has it been renamed or refactored?)" >&2
  exit 1
fi
END_LINE=$((END_LINE - 1))
SCAN_BLOCK=$(sed -n "${START_LINE},${END_LINE}p" "$PUSH_SH")
echo "Extracted push-gate scan block from ${PUSH_SH}:${START_LINE}-${END_LINE} (${END_LINE} - ${START_LINE} + 1 lines)"

case "$SCAN_BLOCK" in
  *'merge-base --is-ancestor'*) ;;
  *)
    echo "FAIL: extracted block does not contain the expected ancestor check (merge-base --is-ancestor) -- has the logic been reverted to strict equality?" >&2
    exit 1
    ;;
esac
case "$SCAN_BLOCK" in
  *'-maxdepth 2'*) ;;
  *)
    echo "FAIL: extracted block does not contain the expected cross-session scan (-maxdepth 2 across all session slots) -- has the lookup been narrowed back to a single session path?" >&2
    exit 1
    ;;
esac

# ── Build a throwaway scratch git repo with a short commit chain ──────────
WORKDIR=$(mktemp -d -t push-gate-ancestor-test-XXXXXX)
trap 'rm -rf "$WORKDIR" "$FAKE_TOKEN_BASE" 2>/dev/null' EXIT INT TERM

REPO="$WORKDIR/scratch-repo"
mkdir -p "$REPO"
git init -q -b test-branch "$REPO"
git -C "$REPO" config user.email "test@example.com"
git -C "$REPO" config user.name "Test"
echo one > "$REPO/file.txt"; git -C "$REPO" add file.txt; git -C "$REPO" commit -q -m "c1"
SHA_C1=$(git -C "$REPO" rev-parse HEAD)
echo two > "$REPO/file.txt"; git -C "$REPO" add file.txt; git -C "$REPO" commit -q -m "c2 (ancestor commit under test)"
SHA_C2=$(git -C "$REPO" rev-parse HEAD)
echo three > "$REPO/file.txt"; git -C "$REPO" add file.txt; git -C "$REPO" commit -q -m "c3 (HEAD)"
SHA_HEAD=$(git -C "$REPO" rev-parse HEAD)

# A commit that is NOT part of this repo's history at all (disjoint branch,
# then abandoned) -- must never validate as an ancestor of SHA_HEAD.
git -C "$REPO" checkout -q -b disjoint-branch "$SHA_C1"
echo disjoint > "$REPO/other.txt"; git -C "$REPO" add other.txt; git -C "$REPO" commit -q -m "disjoint commit"
SHA_DISJOINT=$(git -C "$REPO" rev-parse HEAD)
git -C "$REPO" checkout -q test-branch
git -C "$REPO" branch -q -D disjoint-branch

# _REPO_HASH is derived from realpath(repo_root); using this scratch repo's
# own unique tmpdir path naturally gives a fake-but-real repo-hash that
# cannot collide with any actual repo's real token directory.
_REPO_HASH="$(python3 -c "import hashlib,os; print(hashlib.sha256(os.path.realpath('${REPO}').encode()).hexdigest()[:16])")"
FAKE_TOKEN_BASE="/tmp/agentic-commit/push/${_REPO_HASH}"
_BRANCH="test-branch"

run_scan() {
  # Runs the extracted real scan block in a subshell against $REPO, with
  # $_HEAD_SHA/$_REPO_HASH/$_BRANCH pre-set, and prints the resulting
  # _TOKEN_PATH (empty if no candidate validated).
  (
    cd "$REPO" || exit 1
    _HEAD_SHA="$(git rev-parse HEAD 2>/dev/null)"
    eval "$SCAN_BLOCK"
    echo "TOKEN_PATH_RESULT=[${_TOKEN_PATH}]"
    echo "CANDIDATE_COUNT_RESULT=[${_CANDIDATE_COUNT}]"
  )
}

extract_result() {
  # $1 = full run_scan() output, $2 = marker name
  printf '%s\n' "$1" | grep "^${2}=" | tail -1 | sed -e "s/^${2}=\[//" -e 's/\]$//'
}

write_token() {
  # $1 = subdir under FAKE_TOKEN_BASE (empty string for the legacy session-less
  # path directly under FAKE_TOKEN_BASE), $2 = commit_sha, $3 = session_id to embed
  local subdir="$1" sha="$2" sid="$3" dir
  if [ -n "$subdir" ]; then
    dir="${FAKE_TOKEN_BASE}/${subdir}"
  else
    dir="${FAKE_TOKEN_BASE}"
  fi
  mkdir -p "$dir"
  printf '{"commit_sha": "%s", "branch": "%s", "repo_root": "%s", "session_id": "%s"}' \
    "$sha" "$_BRANCH" "$REPO" "$sid" > "${dir}/${_BRANCH}.json"
}

# ── Scenario A: token commit_sha EQUALS current HEAD (backward-compat case) ──
rm -rf "$FAKE_TOKEN_BASE"
write_token "aaaa1111aaaa1111" "$SHA_HEAD" "session-A"
OUT=$(run_scan)
RESULT=$(extract_result "$OUT" TOKEN_PATH_RESULT)
if [ -n "$RESULT" ]; then
  echo "PASS (A): token with commit_sha == HEAD still validates (backward compatible)"
else
  echo "FAIL (A): token with commit_sha == HEAD did not validate -- $OUT" >&2
  FAIL=1
fi

# ── Scenario B: token commit_sha is an ANCESTOR (not equal) of HEAD ────────
rm -rf "$FAKE_TOKEN_BASE"
write_token "bbbb2222bbbb2222" "$SHA_C1" "session-B"
OUT=$(run_scan)
RESULT=$(extract_result "$OUT" TOKEN_PATH_RESULT)
if [ -n "$RESULT" ]; then
  echo "PASS (B): token with commit_sha = an ancestor (not equal) of HEAD now validates -- this is the core fix"
else
  echo "FAIL (B): token with commit_sha = a real ancestor commit did NOT validate -- ancestor check is missing or broken -- $OUT" >&2
  FAIL=1
fi

# ── Scenario C: token commit_sha is NOT an ancestor of HEAD (disjoint history) ──
rm -rf "$FAKE_TOKEN_BASE"
write_token "cccc3333cccc3333" "$SHA_DISJOINT" "session-C"
OUT=$(run_scan)
RESULT=$(extract_result "$OUT" TOKEN_PATH_RESULT)
if [ -z "$RESULT" ]; then
  echo "PASS (C): token whose commit_sha is NOT an ancestor of HEAD (disjoint branch) is correctly rejected"
else
  echo "FAIL (C): disjoint-history token incorrectly validated as _TOKEN_PATH=[$RESULT] -- ancestor check is not actually discriminating -- $OUT" >&2
  FAIL=1
fi

# ── Scenario D: valid token lives under a DIFFERENT session's subdirectory ──
# (i.e. NOT the calling session's own slot) -- this is the cross-session
# relaxation. We never set any "this is my session" variable at all here,
# proving the scan does not gate on session identity.
rm -rf "$FAKE_TOKEN_BASE"
write_token "dddd4444dddd4444" "$SHA_C2" "some-completely-other-session-nobody-here-owns"
OUT=$(run_scan)
RESULT=$(extract_result "$OUT" TOKEN_PATH_RESULT)
if [ -n "$RESULT" ]; then
  echo "PASS (D): a valid token written under an unrelated session's subdirectory validates without any ownership test -- cross-session relaxation confirmed"
else
  echo "FAIL (D): a valid ancestor token under another session's slot was rejected -- cross-session lookup is missing or broken -- $OUT" >&2
  FAIL=1
fi

# ── Scenario E: malformed token alongside a valid one -- must not abort the scan ──
rm -rf "$FAKE_TOKEN_BASE"
mkdir -p "${FAKE_TOKEN_BASE}/eeee0000eeee0000"
printf 'not valid json{{{' > "${FAKE_TOKEN_BASE}/eeee0000eeee0000/${_BRANCH}.json"
write_token "eeee1111eeee1111" "$SHA_C1" "session-E-valid"
OUT=$(run_scan)
RESULT=$(extract_result "$OUT" TOKEN_PATH_RESULT)
if [ -n "$RESULT" ]; then
  echo "PASS (E): a malformed sibling token is skipped rather than aborting the scan; the valid candidate still wins"
else
  echo "FAIL (E): scan failed to find the valid candidate when a malformed sibling token was also present -- $OUT" >&2
  FAIL=1
fi

# ── Scenario F: no token directory at all -- must fail closed, not crash ──
rm -rf "$FAKE_TOKEN_BASE"
OUT=$(run_scan)
RESULT=$(extract_result "$OUT" TOKEN_PATH_RESULT)
if [ -z "$RESULT" ]; then
  echo "PASS (F): no token directory present -- correctly fails closed (_TOKEN_PATH empty), no crash"
else
  echo "FAIL (F): with no token directory present, _TOKEN_PATH unexpectedly resolved to [$RESULT] -- $OUT" >&2
  FAIL=1
fi

rm -rf "$FAKE_TOKEN_BASE"

if [ "$FAIL" = "0" ]; then
  echo "ALL ASSERTIONS PASSED"
  exit 0
else
  exit 1
fi
