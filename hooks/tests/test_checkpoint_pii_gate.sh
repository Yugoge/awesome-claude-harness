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
#   - AC5/AC6 (review item 5): write_checkpoint refuses a temp index that the
#     pre-commit hook's own checks refuse -- AC5 the private-literal rule (an
#     untracked file holding a listed stand-in literal), AC6 the settings check
#     in a harness-home layout (machine-form settings.json staged without the
#     filter; a UTF-8 byte order mark in front of it with the filter). No new
#     snapshot commit, return code 3, a refusal line in checkpoint.log that holds
#     no literal or value, the failure counter is left alone (review R5: a refusal
#     is not a failure); ordinary snapshots are still written. The byte order mark
#     is refused earlier, by the required clean filter inside `git add -A`: in the
#     harness home that is a refusal too (return code 3, review R5), asked of the
#     clean engine itself; a broken install (engine missing, clean command unset)
#     and a non-harness repository whose filter fails stay ordinary failures (1).
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
# The AKIA-shaped placeholder is printed from two fragments so the tracked file
# itself holds no secret-shaped string; the gate still receives the same bytes.
printf 'contact fake-user@example-fake.test for the demo login\n%s%s\n' 'AKIA' '1234567890ABCDEF' \
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
# AC5 / AC6: snapshots the pre-commit hook's checks refuse are not written.
# ============================================================================
STANDIN="acct-test-123"   # synthetic stand-in literal / personal value
log_file="$CHECKPOINT_LOG_FILE"
fail_count() { local n; n=$(cat "$CHECKPOINT_FAIL_COUNT_FILE" 2>/dev/null | tr -dc '0-9'); printf '%s' "${n:-0}"; }
# _snap <label> <lib> <repo>: one write_checkpoint run in a subshell (sourcing
# <lib>, so the library resolves its harness home from that copy). Sets
# snap_rc, snap_before, snap_after (the checkpoint ref before/after the run)
# and snap_log (what the run appended to checkpoint.log).
_snap() {
  local label="$1" lib="$2" repo="$3" ref lines=0
  ref="refs/checkpoints/$(git -C "$repo" branch --show-current | tr '/' '-')"
  [ -f "$log_file" ] && lines=$(wc -l < "$log_file" | tr -d ' ')
  snap_before=$(git -C "$repo" rev-parse -q --verify "$ref")
  ( . "$lib" && write_checkpoint "$repo" "test: $label" "test: $label" ) >/dev/null 2>&1
  snap_rc=$?
  snap_after=$(git -C "$repo" rev-parse -q --verify "$ref")
  snap_log=$(tail -n "+$((lines + 1))" "$log_file" 2>/dev/null)
}
_refused() {  # <AC> <label> <expected log substring> [<expected rc, default 3>]
  local want="${4:-3}"
  if [ "$snap_rc" -eq "$want" ] && [ "$snap_after" = "$snap_before" ]; then
    _ok "$1: $2 -> rc=$want, no new snapshot commit"
  else
    _fail "$1: $2 -> expected rc=$want and an unchanged ref (rc=$snap_rc, before='$snap_before', after='$snap_after')"
  fi
  if printf '%s' "$snap_log" | grep -qF -- "$3"; then
    _ok "$1: $2 -> checkpoint.log names the reason ('$3')"
  else
    _fail "$1: $2 -> checkpoint.log lacks '$3' (got: $snap_log)"
  fi
  if printf '%s' "$snap_log" | grep -qF -- "$STANDIN"; then
    _fail "$1: $2 -> checkpoint.log prints the stand-in literal/value"
  else
    _ok "$1: $2 -> checkpoint.log holds no literal or value"
  fi
}
_written() {  # <AC> <label>
  if [ "$snap_rc" -eq 0 ] && [ -n "$snap_after" ] && [ "$snap_after" != "$snap_before" ]; then
    _ok "$1: $2 -> new snapshot written"
  else
    _fail "$1: $2 -> expected a new snapshot (rc=$snap_rc, before='$snap_before', after='$snap_after')"
  fi
}

# --- AC5: the private-literal rule (any repository with a non-empty list) ---
REPO3="$WORKDIR/repo3"
mkdir -p "$REPO3"
git init -q "$REPO3"
git -C "$REPO3" config user.name "Test"
git -C "$REPO3" config user.email "test@example.invalid"
printf '/private-literals.txt\n' > "$REPO3/.gitignore"
printf 'hello\n' > "$REPO3/README.md"
git -C "$REPO3" add -A
git -C "$REPO3" commit -q -m "init"
printf '# stand-in list for the test\n%s\n' "$STANDIN" > "$REPO3/private-literals.txt"

printf 'ordinary note\n' > "$REPO3/notes.txt"
_snap "AC5 ordinary" "$CORE_LIB" "$REPO3"
_written AC5 "ordinary untracked file with a list present"

printf 'ticket for %s, demo only\n' "$STANDIN" > "$REPO3/leak.txt"
printf '1\n' > "$CHECKPOINT_FAIL_COUNT_FILE"   # one earlier failure: a refusal neither adds nor resets
count_before=$(fail_count)
_snap "AC5 literal" "$CORE_LIB" "$REPO3"
_refused AC5 "untracked file holding a listed literal" "snapshot refused by the private-literal rule"
if [ "$(fail_count)" -eq "$count_before" ]; then
  _ok "AC5: the refusal is not counted as a checkpoint failure (counter unchanged)"
else
  _fail "AC5: failure counter changed on a refusal (before='${count_before}', after='$(fail_count)')"
fi
if printf '%s' "$snap_log" | grep -qF "leak.txt:1"; then
  _ok "AC5: checkpoint.log names the offending file:line"
else
  _fail "AC5: checkpoint.log does not name leak.txt:1 (got: $snap_log)"
fi

rm -f "$REPO3/leak.txt"
printf 'second note\n' >> "$REPO3/notes.txt"
_snap "AC5 after removal" "$CORE_LIB" "$REPO3"
_written AC5 "the same repository once the literal is gone"
[ "$(fail_count)" = "0" ] && _ok "AC5: success resets the failure counter" \
  || _fail "AC5: failure counter not reset (got '$(fail_count)')"

: > "$REPO3/private-literals.txt"
printf 'ticket for %s, demo only\n' "$STANDIN" > "$REPO3/leak.txt"
_snap "AC5 empty list" "$CORE_LIB" "$REPO3"
_written AC5 "an empty list never refuses"

# --- AC6: the settings check in a harness-home layout -----------------------
H="$WORKDIR/harness"
mkdir -p "$H/hooks/lib" "$H/scripts/install"
cp "$CORE_LIB" "$H/hooks/lib/checkpoint-core.sh"
cp "$REPO_ROOT/scripts/check-public-core.sh" "$H/scripts/check-public-core.sh"
cp "$REPO_ROOT/scripts/install/render-settings" "$H/scripts/install/render-settings"
H_LIB="$H/hooks/lib/checkpoint-core.sh"
git init -q "$H"
git -C "$H" config user.name "Test"
git -C "$H" config user.email "test@example.invalid"
printf '/settings.machine.json\n/private-literals.txt\n' > "$H/.gitignore"
printf '/settings.json filter=claude-settings\n' > "$H/.gitattributes"
printf '{\n  "permissions": {\n    "allow": [\n      "Bash(git status:*)"\n    ]\n  }\n}\n' > "$H/settings.json"
git -C "$H" add -A
git -C "$H" commit -q -m "init"
clean_blob=$(git -C "$H" rev-parse HEAD:settings.json)
printf '{\n  "permissions": {\n    "allow": [\n      "Bash(/home/%s/bin/sync.sh:*)"\n    ]\n  }\n}\n' "$STANDIN" \
  > "$H/settings.machine.json"
# The machine form, as smudge renders it (it also records the applied layer).
(cd "$H" && python3 scripts/install/render-settings smudge < settings.json > settings.json.new) \
  && mv "$H/settings.json.new" "$H/settings.json"
if grep -qF "$STANDIN" "$H/settings.json"; then
  _ok "AC6 setup: working settings.json is in machine form (holds the stand-in)"
else
  _fail "AC6 setup: smudge did not render the stand-in into settings.json"
fi

printf 'ordinary note\n' > "$H/notes.txt"
_snap "AC6 unfiltered" "$H_LIB" "$H"
_refused AC6 "machine-form settings.json staged without the filter" \
  "snapshot refused by the settings check"

for key in clean smudge; do
  git -C "$H" config "filter.claude-settings.$key" "python3 scripts/install/render-settings $key"
done
git -C "$H" config filter.claude-settings.required true
_snap "AC6 filtered" "$H_LIB" "$H"
_written AC6 "machine-form settings.json with the filter registered"
if [ -n "$snap_after" ] && [ "$(git -C "$H" rev-parse "$snap_after:settings.json")" = "$clean_blob" ]; then
  _ok "AC6: the snapshot holds the clean form of settings.json"
else
  _fail "AC6: the snapshot's settings.json is not the clean form"
fi

{ printf '\357\273\277'; cat "$H/settings.json"; } > "$H/settings.json.new" && mv "$H/settings.json.new" "$H/settings.json"
printf 'second note\n' >> "$H/notes.txt"
printf '1\n' > "$CHECKPOINT_FAIL_COUNT_FILE"   # one earlier failure: a refusal neither adds nor resets
_snap "AC6 BOM" "$H_LIB" "$H"
_refused AC6 "UTF-8 byte order mark in front of the machine form (filter registered)" \
  "snapshot refused by the settings filter (render-settings clean): nothing written"
if printf '%s' "$snap_log" | grep -qF "byte order mark" && [ "$(fail_count)" = 1 ]; then
  _ok "AC6: the filter's reason is logged and the BOM refusal leaves the failure counter alone"
else
  _fail "AC6: BOM refusal: reason missing from the log or counter changed (count='$(fail_count)', log: $snap_log)"
fi

# A broken install is not a refusal: the snapshot still fails (rc 1) and is counted.
mv "$H/scripts/install/render-settings" "$H/render-settings.away"
_snap "AC6 engine missing" "$H_LIB" "$H"
_refused AC6 "clean filter registered, its engine missing (broken install)" "add -A failed" 1
mv "$H/render-settings.away" "$H/scripts/install/render-settings"
git -C "$H" config --unset filter.claude-settings.clean
_snap "AC6 clean unset" "$H_LIB" "$H"
_refused AC6 "required filter registered without a clean command (broken install)" "add -A failed" 1
git -C "$H" config filter.claude-settings.clean "python3 scripts/install/render-settings clean"
[ "$(fail_count)" = 3 ] && _ok "AC6: both broken-install failures are counted (1 -> 3)" \
  || _fail "AC6: broken-install failures not counted (got '$(fail_count)')"

# Outside the harness home a failing filter on a settings.json stays an ordinary failure.
REPO4="$WORKDIR/repo4"
git init -q "$REPO4"
git -C "$REPO4" config user.name "Test"
git -C "$REPO4" config user.email "test@example.invalid"
printf '/settings.json filter=claude-settings\n' > "$REPO4/.gitattributes"
git -C "$REPO4" add -A
git -C "$REPO4" commit -q -m "init"
git -C "$REPO4" config filter.claude-settings.clean "python3 $H/scripts/install/render-settings clean"
git -C "$REPO4" config filter.claude-settings.required true
cp "$H/settings.json" "$REPO4/settings.json"   # still holds the byte order mark
_snap "AC6 other repository" "$H_LIB" "$REPO4"
_refused AC6 "another repository whose settings filter fails staging" "add -A failed" 1

# Once the byte order mark is gone the next snapshot is written again.
tail -c +4 "$H/settings.json" > "$H/settings.json.new" && mv "$H/settings.json.new" "$H/settings.json"
_snap "AC6 BOM removed" "$H_LIB" "$H"
_written AC6 "the machine form again, byte order mark removed"

# ============================================================================
# AC7: the pre-push gate runs the engine's private-literal rule over the new
# blobs, so a snapshot written before its literal was listed is not pushed.
# ============================================================================
REPO5="$WORKDIR/repo5"; ORIGIN5="$WORKDIR/origin5.git"
git init -q "$REPO5"; git init -q --bare "$ORIGIN5"
git -C "$REPO5" config user.name "Test"
git -C "$REPO5" config user.email "test@example.invalid"
printf '/private-literals.txt\n' > "$REPO5/.gitignore"
git -C "$REPO5" add -A && git -C "$REPO5" commit -q -m "init"
printf 'ticket for %s, demo only\n' "$STANDIN" > "$REPO5/early.txt"
_snap "AC7 before listing" "$CORE_LIB" "$REPO5"
_written AC7 "a literal not yet listed"
printf '%s\n' "$STANDIN" > "$REPO5/private-literals.txt"
git -C "$REPO5" remote add origin "$ORIGIN5"
ref5="refs/checkpoints/$(git -C "$REPO5" branch --show-current)"
lines=$(wc -l < "$push_log" 2>/dev/null | tr -d ' ')
_checkpoint_push_worker "$REPO5" "$ref5" "$snap_after"
alert=$(tail -n "+$((${lines:-0} + 1))" "$push_log" 2>/dev/null)
if [ -z "$(git --git-dir="$ORIGIN5" rev-parse -q --verify "$ref5")" ] \
  && printf '%s' "$alert" | grep -q "ALERT.*the private-literal rule.*early.txt:1" \
  && ! printf '%s' "$alert" | grep -qF -- "$STANDIN"; then
  _ok "AC7: push refused naming the private-literal rule and early.txt:1, literal not logged"
else
  _fail "AC7: snapshot holding a since-listed literal was pushed or misreported (log: $alert)"
fi

# ============================================================================
if [ "$FAILS" -eq 0 ]; then
  echo "ALL ASSERTIONS PASS (AC1, AC2, AC3, AC4, AC5, AC6, AC7)"
  exit 0
else
  echo "$FAILS assertion(s) failed" >&2
  exit 1
fi
