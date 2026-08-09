#!/usr/bin/env bash
# overnight-git-env.sh — prepare the overnight actor's git PATH + env (M11/AC9).
#
# Builds a per-launch bin dir whose `git` is the MODERN-GIT SELECTOR (puts the
# pinned >=2.46 distribution first, else system git) and ALSO installs the
# SEPARATE policy shim. The selector dir is prepended to PATH ahead of system
# git, so the overnight actor's `git` resolves to harness-owned wrappers.
#
# It exports the overnight-actor markers the keystone + policy shim key on:
#   CLAUDE_OVERNIGHT_ACTOR=1
#   CLAUDE_OVERNIGHT_MAIN_ROOT=<main_root>
# and NEVER sets CLAUDE_GIT_BLESSED_TOKEN (the overnight env must not hold it).
#
# Usage (source it):  source overnight-git-env.sh --main-root <m> --worktree <w>
# Output (when not sourced): prints export lines to stdout.
# The selector is SEPARATE from the policy shim (codex round-2 #7): two files,
# so relaxing policy never drops the selector.

# NOTE: do NOT `set -e` unconditionally — this script is meant to be SOURCED by
# the overnight actor (fix-1), and `set -e` would leak into the actor's shell.
# Use BASH_SOURCE[0] (correct whether sourced or executed; $0 is the SOURCING
# shell when sourced, which broke the relative SRC_DIR resolution).
_OGE_SELF="${BASH_SOURCE[0]:-$0}"
_OGE_DIR="$(cd "$(dirname "$_OGE_SELF")" && pwd -P)"

MAIN_ROOT=""
WORKTREE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --main-root) MAIN_ROOT="$2"; shift 2 ;;
    --worktree) WORKTREE="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[[ -n "$MAIN_ROOT" ]] || { echo "Error: --main-root required" >&2; return 1 2>/dev/null || exit 1; }

SRC_DIR="$_OGE_DIR/overnight-git"
BIN_DIR="${CLAUDE_OVERNIGHT_GIT_BINDIR:-$MAIN_ROOT/.claude/overnight-git-bin}"
SHIM_DIR="${CLAUDE_OVERNIGHT_GIT_POLICY_BINDIR:-$MAIN_ROOT/.claude/overnight-git-policy-bin}"

# VERIFY FIRST, INSTALL ONLY IF NEEDED.
# Both wrappers live under the MAIN root. The overnight ACTOR sources this file
# from inside an armed boundary that RO-binds that root, so an unconditional
# `mkdir -p` + `install` re-installed already-correct files and emitted
#   install: cannot remove '.../overnight-git-bin/git': Read-only file system
# on every source — the user's reported first symptom of this same root cause.
# The launcher now provisions these pre-boundary, so by the time the actor
# sources this the healthy path must perform ZERO write attempts.
_oge_wrapper_ok() {  # $1 = installed path, $2 = source path
    [[ -f "$1" && ! -L "$1" && -x "$1" ]] && cmp -s "$1" "$2"
}
_oge_provisioned() {
    _oge_wrapper_ok "$BIN_DIR/git" "$SRC_DIR/git-selector" \
        && _oge_wrapper_ok "$SHIM_DIR/git" "$SRC_DIR/git-policy-shim"
}

if ! _oge_provisioned; then
    # Absent or corrupt. Repair is attempted, but it is allowed to FAIL: under an
    # armed boundary it always will, and that must fail CLOSED rather than leave
    # a half-applied environment behind.
    mkdir -p "$BIN_DIR" 2>/dev/null || true
    # `git` on PATH == the SELECTOR (puts modern git first, else system git).
    install -m 0755 "$SRC_DIR/git-selector" "$BIN_DIR/git" 2>/dev/null || true
    # the policy shim is installed under its own name AND chained: the selector
    # delegates to the real git; the shim enforces policy. We name the shim `git`
    # inside a policy-prefixed dir so it runs FIRST, then delegates to the
    # selector as its real git.
    mkdir -p "$SHIM_DIR" 2>/dev/null || true
    install -m 0755 "$SRC_DIR/git-policy-shim" "$SHIM_DIR/git" 2>/dev/null || true
fi

# ALL-OR-NOTHING. Every export below, plus the blessed-token unset, is applied
# only AFTER the wrappers are known good. A partial transition is the dangerous
# state: PATH pointing at a missing shim, or CLAUDE_OVERNIGHT_ACTOR set without
# CLAUDE_OVERNIGHT_WORKTREE, leaves the shim unable to classify "under main_root
# but outside the worktree" and silently stops enforcing.
if ! _oge_provisioned; then
    echo "Error: overnight git wrappers are absent or corrupt and could not be repaired." >&2
    echo "       Expected: $SHIM_DIR/git and $BIN_DIR/git" >&2
    echo "       Environment left UNCHANGED (no PATH, marker or token mutation)." >&2
    return 1 2>/dev/null || exit 1
fi

# Order on PATH: policy shim FIRST (enforces), then selector (modern git), then
# system. The shim's real-git is the selector (via CLAUDE_OVERNIGHT_REAL_GIT).
# Drop the blessed token FIRST, and verify it actually went. `unset` fails on a
# readonly variable, and swallowing that failure would hand the overnight actor a
# shim-first PATH while it still holds the token the overnight env must not have
# (:12) — enforcement bypassed by a variable the caller made readonly. This is a
# mutation, so it belongs on the same all-or-nothing side as the exports.
unset CLAUDE_GIT_BLESSED_TOKEN 2>/dev/null || true
if [[ -n "${CLAUDE_GIT_BLESSED_TOKEN+x}" ]]; then
    echo "Error: CLAUDE_GIT_BLESSED_TOKEN could not be unset (readonly?); refusing to arm the overnight git env." >&2
    echo "       Environment left UNCHANGED (no PATH or marker mutation)." >&2
    return 1 2>/dev/null || exit 1
fi
export CLAUDE_OVERNIGHT_ACTOR=1
export CLAUDE_OVERNIGHT_MAIN_ROOT="$MAIN_ROOT"
# fix-3 (Cycle-2): the shim's main-targeting predicate needs the worktree root to
# classify "under main_root but outside the worktree" as main-targeting.
[[ -n "$WORKTREE" ]] && export CLAUDE_OVERNIGHT_WORKTREE="$WORKTREE"
export CLAUDE_OVERNIGHT_REAL_GIT="$BIN_DIR/git"   # shim delegates to the selector
export PATH="$SHIM_DIR:$BIN_DIR:$PATH"

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  # Not sourced: emit export lines for eval (fix-1: the launcher now CONSUMES
  # this output and persists it; dev-overnight.md Step 1 sources it directly).
  echo "export CLAUDE_OVERNIGHT_ACTOR=1;"
  echo "export CLAUDE_OVERNIGHT_MAIN_ROOT=$MAIN_ROOT;"
  [[ -n "$WORKTREE" ]] && echo "export CLAUDE_OVERNIGHT_WORKTREE=$WORKTREE;"
  echo "export CLAUDE_OVERNIGHT_REAL_GIT=$BIN_DIR/git;"
  echo "unset CLAUDE_GIT_BLESSED_TOKEN;"
  echo "export PATH=$SHIM_DIR:$BIN_DIR:\$PATH;"
  # fix-1: a stable, machine-readable marker so the launcher can capture the
  # resolved policy-shim git path + bindirs into the state file for AC-1.
  echo "# OVERNIGHT_GIT_ENV_SHIM_GIT=$SHIM_DIR/git"
  echo "# OVERNIGHT_GIT_ENV_BINDIR=$BIN_DIR"
  echo "# OVERNIGHT_GIT_ENV_SHIMDIR=$SHIM_DIR"
fi
