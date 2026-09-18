#!/usr/bin/env bash
# Regression tests for the checkpoint PII/credential hard-exclude + push gate
# (M1/M2/M3/S1, ticket dev-20260918-084500; AC1-AC5 in
# docs/dev/acceptance-criteria-20260918-084500.json).
#
# Strategy:
#   - AC1/AC2: build a real tmp git repo, populate it with fixtures at known
#     PII-class paths (.claude.json, a nested backups/ path, a nested
#     sessions/ path) plus an ordinary file, call write_checkpoint(), and
#     inspect the resulting snapshot tree via `git ls-tree -r` -- proving the
#     hard-exclude works independent of .gitignore (this tmp repo has NO
#     .gitignore at all, so nothing here is inherited from ignore rules).
#     AC2 is a static grep confirming the add-all invocation still carries no
#     ignore-bypassing option.
#   - AC3/AC4: build a tmp git repo with a REAL local bare "origin" remote
#     (a filesystem path -- no network, no mocking of git internals
#     required). Call the newly-extracted `_checkpoint_push_worker()`
#     directly and SYNCHRONOUSLY (bypassing the production background+disown
#     wrapper in `_checkpoint_rate_limited_push()`, which would otherwise
#     make deterministic assertions racy) with a benign local tip first
#     (positive control, AC4) and then a PII-bearing one (AC3), and observe
#     ground truth: did the bare origin's checkpoint ref actually advance,
#     and did the push log gain an ALERT line. This is a stronger
#     verification than a PATH-shimmed mock (it exercises real git plumbing
#     end-to-end) while still never touching the network.
#
# Usage: bash hooks/tests/test_checkpoint_pii_gate.sh
# Exit:  0 = all assertions pass; 1 = any assertion failed.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CORE_LIB="${REPO_ROOT}/hooks/lib/checkpoint-core.sh"
if [ ! -f "$CORE_LIB" ]; then
  echo "FAIL: cannot find $CORE_LIB" >&2
  exit 1
fi

FAILS=0
_fail() { echo "FAIL: $*" >&2; FAILS=$((FAILS + 1)); }
_ok() { echo "OK: $*"; }

WORKDIR=$(mktemp -d -t checkpoint-pii-gate-test-XXXXXX)
trap 'rm -rf "$WORKDIR" 2>/dev/null' EXIT INT TERM

export CHECKPOINT_LOG_DIR="$WORKDIR/logs"
# Fast local-only lookups; no real network call happens anywhere below (the
# only "remote" is a local bare repo path).
export CHECKPOINT_REMOTE_LOOKUP_TIMEOUT=5
# Pre-create the log dir: write_checkpoint()'s early plumbing steps
# (read-tree/add-A/write-tree) redirect stderr directly to
# "$CHECKPOINT_LOG_FILE" via `2>>`, which requires the parent directory to
# already exist -- true in real installs (~/.claude/logs is long-lived) but
# not in a from-scratch test sandbox. Pre-creating it here is a test-harness
# concern only; production callers are unaffected and this file makes no
# production-code change for it (out of this ticket's locked scope).
mkdir -p "$CHECKPOINT_LOG_DIR"

# shellcheck source=../lib/checkpoint-core.sh
. "$CORE_LIB"

# ============================================================================
# AC2 (static): the add-all invocation in write_checkpoint() must remain
# unflagged -- no ignore-bypassing option co-occurring on that logical call.
# ============================================================================
add_a_line=$(grep -n '\$git_cmd add -A' "$CORE_LIB" | head -1)
if [ -n "$add_a_line" ] && ! printf '%s' "$add_a_line" | grep -q -- '-f'; then
  _ok "AC2: git add -A in write_checkpoint carries no -f (ignore-bypass) flag"
else
  _fail "AC2: expected an unflagged '\$git_cmd add -A' invocation in $CORE_LIB (got: '${add_a_line}')"
fi

# ============================================================================
# AC1: hard-exclude independent of .gitignore
# ============================================================================
REPO1="$WORKDIR/repo1"
mkdir -p "$REPO1"
git init -q "$REPO1"
git -C "$REPO1" config user.name "Test"
git -C "$REPO1" config user.email "test@example.invalid"
printf 'hello\n' > "$REPO1/README.md"
git -C "$REPO1" add README.md
git -C "$REPO1" commit -q -m "init"

# NOTE: this repo intentionally has NO .gitignore -- proving the exclusion is
# independent of .gitignore content, not merely inherited from it.
mkdir -p "$REPO1/configs/backups" "$REPO1/state/nested/sessions"
printf '{"oauthAccount":{"email":"fake-pii@example.test","userID":"u-0001"}}\n' \
  > "$REPO1/.claude.json"
printf 'fake fixture payload one\n' > "$REPO1/configs/backups/dump.txt"
printf 'fake fixture payload two\n' > "$REPO1/state/nested/sessions/replay.txt"
printf 'ordinary tracked content\n' > "$REPO1/notes.txt"

write_checkpoint "$REPO1" "test: AC1 fixture" "test checkpoint 1" >/dev/null 2>&1
rc=$?
branch1=$(git -C "$REPO1" branch --show-current)
ref1="refs/checkpoints/${branch1}"
sha1=$(git -C "$REPO1" rev-parse --verify -q "$ref1")

if [ "$rc" -ne 0 ] || [ -z "$sha1" ]; then
  _fail "AC1: write_checkpoint did not produce a checkpoint ref (rc=$rc)"
else
  tree_paths=$(git -C "$REPO1" ls-tree -r --name-only "$sha1")
  if printf '%s\n' "$tree_paths" | grep -qx '\.claude\.json'; then
    _fail "AC1: .claude.json present in snapshot tree (should be hard-excluded)"
  else
    _ok "AC1: .claude.json absent from snapshot tree"
  fi
  if printf '%s\n' "$tree_paths" | grep -q 'configs/backups/dump.txt'; then
    _fail "AC1: configs/backups/dump.txt present in snapshot tree (backups/ component should be hard-excluded)"
  else
    _ok "AC1: configs/backups/dump.txt absent from snapshot tree"
  fi
  if printf '%s\n' "$tree_paths" | grep -q 'state/nested/sessions/replay.txt'; then
    _fail "AC1: state/nested/sessions/replay.txt present in snapshot tree (sessions/ component should be hard-excluded)"
  else
    _ok "AC1: state/nested/sessions/replay.txt absent from snapshot tree"
  fi
  if printf '%s\n' "$tree_paths" | grep -qx 'notes.txt'; then
    _ok "AC1 (scope check): ordinary notes.txt still captured (exclude is targeted, not overly broad)"
  else
    _fail "AC1 (scope check): ordinary notes.txt missing from snapshot tree -- exclude is too broad"
  fi
fi

# ============================================================================
# AC3 / AC4: fail-closed PII/credential push gate + positive control.
#
# Uses a REAL local bare "origin" (filesystem path, no network) so the
# push-or-not decision is verified against ground truth (did the remote ref
# actually advance) rather than a mocked binary's invocation count.
# ============================================================================
REPO2="$WORKDIR/repo2"
ORIGIN2="$WORKDIR/origin2.git"
mkdir -p "$REPO2"
git init -q "$REPO2"
git -C "$REPO2" config user.name "Test"
git -C "$REPO2" config user.email "test@example.invalid"
printf 'hello\n' > "$REPO2/README.md"
git -C "$REPO2" add README.md
git -C "$REPO2" commit -q -m "init"
git init -q --bare "$ORIGIN2"

branch2=$(git -C "$REPO2" branch --show-current)
ref2="refs/checkpoints/${branch2}"
push_log="$CHECKPOINT_PUSH_LOG_FILE"

# --- Checkpoint 1 (benign content only): positive control (AC4) ---
# write_checkpoint() is idempotent: an unchanged working tree (== HEAD's
# tree) produces no new checkpoint commit at all. Add an ordinary,
# PII-free, UNCOMMITTED file first so this checkpoint actually differs
# from HEAD and a real ref gets created.
printf 'ordinary changelog line one\n' > "$REPO2/changelog.txt"
# Build WITHOUT origin configured so write_checkpoint's own auto-triggered
# background push never fires (it no-ops when 'origin' is absent); this
# keeps our own direct, synchronous _checkpoint_push_worker call below
# deterministic (no race with a backgrounded push attempt).
write_checkpoint "$REPO2" "test: AC4 baseline" "checkpoint 1 (benign)" >/dev/null 2>&1
git -C "$REPO2" remote add origin "$ORIGIN2"
local_sha_1=$(git -C "$REPO2" rev-parse --verify -q "$ref2")
if [ -z "$local_sha_1" ]; then
  _fail "AC4 setup: checkpoint 1 did not produce a ref (write_checkpoint no-op?)"
fi

lines_before=0
[ -f "$push_log" ] && lines_before=$(wc -l < "$push_log" | tr -d ' ')

_checkpoint_push_worker "$REPO2" "$ref2" "$local_sha_1"

origin_sha_after_benign=$(git --git-dir="$ORIGIN2" rev-parse --verify -q "$ref2" 2>/dev/null)
if [ "$origin_sha_after_benign" = "$local_sha_1" ]; then
  _ok "AC4: benign checkpoint 1 pushed to origin as expected (positive control: no false-positive block)"
else
  _fail "AC4: benign checkpoint 1 was NOT pushed to origin (expected ${local_sha_1}, got '${origin_sha_after_benign}')"
fi
lines_after_benign=0
[ -f "$push_log" ] && lines_after_benign=$(wc -l < "$push_log" | tr -d ' ')
if [ "$lines_after_benign" -gt "$lines_before" ] && grep -q ALERT "$push_log" 2>/dev/null; then
  _fail "AC4: unexpected ALERT logged for benign baseline push"
else
  _ok "AC4: no ALERT logged for benign baseline push"
fi

# --- Checkpoint 2: add a PII/credential-shaped fixture, expect BLOCK (AC3) ---
git -C "$REPO2" remote remove origin
printf 'contact fake-user@example-fake.test for the demo login\nAKIA1234567890ABCDEF\n' \
  > "$REPO2/incident-fixture.txt"
write_checkpoint "$REPO2" "test: AC3 fixture" "checkpoint 2 (PII-shaped)" >/dev/null 2>&1
git -C "$REPO2" remote add origin "$ORIGIN2"
local_sha_2=$(git -C "$REPO2" rev-parse --verify -q "$ref2")
if [ -z "$local_sha_2" ] || [ "$local_sha_2" = "$local_sha_1" ]; then
  _fail "AC3 setup: checkpoint 2 did not produce a new ref distinct from checkpoint 1"
fi

_checkpoint_push_worker "$REPO2" "$ref2" "$local_sha_2"

origin_sha_after_pii=$(git --git-dir="$ORIGIN2" rev-parse --verify -q "$ref2" 2>/dev/null)
if [ "$origin_sha_after_pii" = "$local_sha_1" ]; then
  _ok "AC3: origin checkpoint ref did NOT advance past the benign baseline (PII-shaped push blocked)"
else
  _fail "AC3: origin checkpoint ref advanced to '${origin_sha_after_pii}' (expected it to stay at ${local_sha_1} -- PII-shaped push should have been blocked)"
fi
if grep -q "ALERT" "$push_log" 2>/dev/null; then
  _ok "AC3: ALERT-level line present in checkpoint push log after PII-shaped push attempt"
else
  _fail "AC3: no ALERT line found in checkpoint push log after PII-shaped push attempt"
fi

# ============================================================================
if [ "$FAILS" -eq 0 ]; then
  echo "ALL ASSERTIONS PASS (AC1, AC2, AC3, AC4)"
  exit 0
else
  echo "$FAILS assertion(s) failed" >&2
  exit 1
fi
