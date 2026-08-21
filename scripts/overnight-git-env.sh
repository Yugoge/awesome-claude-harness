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
mkdir -p "$BIN_DIR"
# `git` on PATH == the SELECTOR (puts modern git first, else system git).
install -m 0755 "$SRC_DIR/git-selector" "$BIN_DIR/git"
# the policy shim is installed under its own name AND chained: the selector
# delegates to the real git; the shim enforces policy. We name the shim `git`
# inside a policy-prefixed dir so it runs FIRST, then delegates to the selector
# as its real git.
SHIM_DIR="${CLAUDE_OVERNIGHT_GIT_POLICY_BINDIR:-$MAIN_ROOT/.claude/overnight-git-policy-bin}"
mkdir -p "$SHIM_DIR"
install -m 0755 "$SRC_DIR/git-policy-shim" "$SHIM_DIR/git"

# Order on PATH: policy shim FIRST (enforces), then selector (modern git), then
# system. The shim's real-git is the selector (via CLAUDE_OVERNIGHT_REAL_GIT).
export CLAUDE_OVERNIGHT_ACTOR=1
export CLAUDE_OVERNIGHT_MAIN_ROOT="$MAIN_ROOT"
# fix-3 (Cycle-2): the shim's main-targeting predicate needs the worktree root to
# classify "under main_root but outside the worktree" as main-targeting.
[[ -n "$WORKTREE" ]] && export CLAUDE_OVERNIGHT_WORKTREE="$WORKTREE"
export CLAUDE_OVERNIGHT_REAL_GIT="$BIN_DIR/git"   # shim delegates to the selector
unset CLAUDE_GIT_BLESSED_TOKEN 2>/dev/null || true
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
