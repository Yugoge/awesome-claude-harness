#!/usr/bin/env bash
# Regression test for hooks/push.sh R22 (line ~375): HAS_UPSTREAM must be
# assigned via an exit-status-guarded form (`|| HAS_UPSTREAM=""`) so that a
# HALF-CONFIGURED upstream -- branch.<name>.remote/.merge set, but the
# matching remote-tracking ref deleted/pruned (e.g. the upstream branch was
# deleted on the remote) -- does not leave HAS_UPSTREAM holding the LITERAL
# STRING `@{u}` (a non-empty, truthy value that misroutes push.sh into the
# "has upstream" branch with a bogus ref).
#
# Root cause (verified against the installed git, `git --version`): when
# upstream CONFIG exists (branch.*.remote/.merge) but the underlying
# remote-tracking ref is gone, `git rev-parse --abbrev-ref
# --symbolic-full-name @{u}` fails (exit 128) but still echoes the literal
# argument `@{u}` to STDOUT -- even under `2>/dev/null`. This is a distinct,
# narrower failure mode than "upstream never configured" (which produces
# EMPTY stdout for both old and new forms and is NOT a regression
# discriminator -- that was this test's previous, incorrect scenario).
#
# This test:
#   1. Builds a throwaway scratch repo: real commit, real remote, `push -u`
#      (creates both branch.<name>.remote/.merge config AND a
#      remote-tracking ref), then deletes ONLY the remote-tracking ref --
#      reproducing the exact half-configured-but-deleted-ref scenario.
#   2. Extracts the REAL guarded assignment line VERBATIM from the live
#      hooks/push.sh (grep anchor + sed, not a hand-copied duplicate) and
#      `eval`s it against that scratch repo. Asserts HAS_UPSTREAM ends up
#      empty. If a future edit removes the `|| HAS_UPSTREAM=""` guard from
#      hooks/push.sh, this extraction picks up the regressed line and the
#      assertion fails.
#   3. Negative control: derives the OLD (unguarded) form by stripping the
#      trailing `|| HAS_UPSTREAM=""` clause from the SAME extracted text
#      (not hand-typed) and evals it in the same repo. Asserts HAS_UPSTREAM
#      ends up the literal string `@{u}` (non-empty/truthy) -- proving this
#      scenario actually discriminates a regression.
#
# No `set -e` is used anywhere (hooks/push.sh itself never runs under
# `set -e` -- see its full-file grep), so this test does not rely on abort
# semantics that production never exercises.
#
# Usage: bash hooks/tests/test_push_no_upstream_guard.sh
# Exit:  0 = both assertions pass; 1 = either assertion failed.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PUSH_SH="${REPO_ROOT}/hooks/push.sh"
if [ ! -f "$PUSH_SH" ]; then
  echo "FAIL: cannot find $PUSH_SH" >&2
  exit 1
fi

FAIL=0

# ── Extract the REAL guarded assignment line verbatim from hooks/push.sh ──
ANCHOR='HAS_UPSTREAM=$(git rev-parse --abbrev-ref --symbolic-full-name @{u}'
LINE_NUM=$(grep -nF "$ANCHOR" "$PUSH_SH" | head -1 | cut -d: -f1)
if [ -z "$LINE_NUM" ]; then
  echo "FAIL: could not locate the HAS_UPSTREAM @{u} assignment in $PUSH_SH (anchor text not found -- has it been renamed or refactored?)" >&2
  exit 1
fi
REAL_LINE=$(sed -n "${LINE_NUM}p" "$PUSH_SH" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')

case "$REAL_LINE" in
  HAS_UPSTREAM=*'git rev-parse'*'@{u}'*) ;;
  *)
    echo "FAIL: extracted line does not look like the expected assignment: [$REAL_LINE]" >&2
    exit 1
    ;;
esac
echo "Extracted from ${PUSH_SH}:${LINE_NUM}: $REAL_LINE"

# ── Build the throwaway half-configured-upstream scratch repo ─────────────
WORKDIR=$(mktemp -d -t push-no-upstream-test-XXXXXX)
trap 'rm -rf "$WORKDIR" 2>/dev/null' EXIT INT TERM

BARE="$WORKDIR/bare-remote.git"
git init -q --bare "$BARE"

REPO="$WORKDIR/local-repo"
mkdir -p "$REPO"
git init -q -b test-branch "$REPO"
git -C "$REPO" config user.email "test@example.com"
git -C "$REPO" config user.name "Test"
echo hello > "$REPO/file.txt"
git -C "$REPO" add file.txt
git -C "$REPO" commit -q -m "initial"
git -C "$REPO" remote add origin "$BARE"
git -C "$REPO" push -q -u origin test-branch

# Delete ONLY the remote-tracking ref; branch.test-branch.remote/.merge
# config remnants stay in place -- this is the half-configured scenario.
rm -f "$REPO/.git/refs/remotes/origin/test-branch"
if [ -f "$REPO/.git/packed-refs" ]; then
  sed -i '/refs\/remotes\/origin\/test-branch/d' "$REPO/.git/packed-refs"
fi

# Sanity check the scratch repo actually reproduces the target scenario.
if [ -z "$(git -C "$REPO" config --get branch.test-branch.remote 2>/dev/null)" ]; then
  echo "FAIL: scratch repo setup broken -- branch.test-branch.remote is not set" >&2
  FAIL=1
fi
if git -C "$REPO" rev-parse --verify -q refs/remotes/origin/test-branch >/dev/null 2>&1; then
  echo "FAIL: scratch repo setup broken -- remote-tracking ref still exists (deletion failed)" >&2
  FAIL=1
fi

# ── Assertion (a): the REAL guarded line, evaluated against the broken repo ──
(
  cd "$REPO" || exit 1
  unset HAS_UPSTREAM
  eval "$REAL_LINE"
  echo "HAS_UPSTREAM_NEW=[${HAS_UPSTREAM}]"
) > "$WORKDIR/new-out"
NEW_MARKER=$(grep '^HAS_UPSTREAM_NEW=' "$WORKDIR/new-out")

if [ -z "$NEW_MARKER" ]; then
  echo "FAIL: real guarded line did not produce output (subshell setup failure) -- see $WORKDIR/new-out" >&2
  FAIL=1
else
  NEW_VALUE=$(printf '%s\n' "$NEW_MARKER" | sed -e 's/^HAS_UPSTREAM_NEW=\[//' -e 's/\]$//')
  if [ -n "$NEW_VALUE" ]; then
    echo "FAIL: real hooks/push.sh:${LINE_NUM} guarded form left HAS_UPSTREAM=[${NEW_VALUE}] (expected empty) in the half-configured/deleted-ref scenario -- the || guard is missing or broken" >&2
    FAIL=1
  else
    echo "PASS: guarded HAS_UPSTREAM assignment (extracted from hooks/push.sh) yields empty value in the half-configured/deleted-ref scenario"
  fi
fi

# ── Assertion (b, negative control): OLD unguarded form must leak '@{u}' ──
GUARD_SUFFIX=' || HAS_UPSTREAM=""'
OLD_LINE="${REAL_LINE%$GUARD_SUFFIX}"
if [ "$OLD_LINE" = "$REAL_LINE" ]; then
  echo "FAIL: could not strip the || HAS_UPSTREAM=\"\" guard suffix from the extracted line -- negative control cannot be constructed: [$REAL_LINE]" >&2
  FAIL=1
else
  (
    cd "$REPO" || exit 1
    unset HAS_UPSTREAM
    eval "$OLD_LINE"
    echo "HAS_UPSTREAM_OLD=[${HAS_UPSTREAM}]"
  ) > "$WORKDIR/old-out"
  OLD_MARKER=$(grep '^HAS_UPSTREAM_OLD=' "$WORKDIR/old-out")

  if [ -z "$OLD_MARKER" ]; then
    echo "FAIL: old (unguarded) form did not produce output (subshell setup failure) -- see $WORKDIR/old-out" >&2
    FAIL=1
  else
    OLD_VALUE=$(printf '%s\n' "$OLD_MARKER" | sed -e 's/^HAS_UPSTREAM_OLD=\[//' -e 's/\]$//')
    if [ "$OLD_VALUE" != '@{u}' ]; then
      echo "FAIL: old (unguarded) form did not leak the literal '@{u}' string as expected (got HAS_UPSTREAM=[${OLD_VALUE}]) -- negative control failed; this scenario would not discriminate a regression" >&2
      FAIL=1
    else
      echo "PASS: unguarded negative-control form leaks HAS_UPSTREAM=[@{u}] (non-empty/truthy) in the same scenario -- confirms this test discriminates a real regression"
    fi
  fi
fi

if [ "$FAIL" = "0" ]; then
  echo "ALL ASSERTIONS PASSED"
  exit 0
else
  exit 1
fi
