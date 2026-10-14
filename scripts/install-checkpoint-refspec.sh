#!/usr/bin/env bash
# install-checkpoint-refspec.sh — idempotently add refs/checkpoints/* to
# remote.origin.fetch so `git fetch` also pulls cross-machine checkpoints.
# ----------------------------------------------------------------------------
# Installed 2026-04-16 (SaaS-grade blame-hygiene audit — ops gap O4).
#
# Purpose
#   checkpoint-core.sh pushes refs/checkpoints/<branch> in the background only
#   when GIT_AUTO_PUSH=1 (off by default; otherwise checkpoints stay local).
#   A default git clone only fetches refs/heads/*. This script adds the extra
#   refspec so team members see each other's pushed checkpoints under
#   refs/remotes/origin/checkpoints/*.
#
# Usage
#   install-checkpoint-refspec.sh [<repo-path>]
#     <repo-path>  defaults to $PWD
#
# Exit codes
#   0  refspec installed (or already present — idempotent)
#   1  not a git repo, or no 'origin' remote, or config write failed
#
# Safety
#   - duplicate guard via `git config --get-all` (exact-match grep)
#   - uses `git config --add` (append-only; does not clobber existing refspecs)
# ----------------------------------------------------------------------------

set -euo pipefail

REPO="${1:-$(pwd)}"
REFSPEC='+refs/checkpoints/*:refs/remotes/origin/checkpoints/*'

if [ ! -d "$REPO" ]; then
    echo "Error: repo path does not exist: $REPO" >&2
    exit 1
fi

cd "$REPO"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "Error: $REPO is not a git repository" >&2
    exit 1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
    echo "Error: no 'origin' remote configured in $REPO" >&2
    echo "Hint: add one with 'git remote add origin <url>' first" >&2
    exit 1
fi

# Duplicate guard: look for the exact refspec string among existing fetch refs.
# `git config --get-all` may list multiple lines; we match the exact value.
if git config --get-all remote.origin.fetch 2>/dev/null | grep -Fxq "$REFSPEC"; then
    echo "already configured: remote.origin.fetch already includes '$REFSPEC' in $REPO"
    exit 0
fi

if ! git config --add remote.origin.fetch "$REFSPEC"; then
    echo "Error: failed to add refspec to git config in $REPO" >&2
    exit 1
fi

echo "installed: remote.origin.fetch += '$REFSPEC' in $REPO"
echo "Next step: run 'git fetch origin' to pull checkpoint refs from the remote."
exit 0
