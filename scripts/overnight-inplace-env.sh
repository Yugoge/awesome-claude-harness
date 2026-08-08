#!/usr/bin/env bash
# overnight-inplace-env.sh — export the overnight ACTOR MARKER, and nothing else.
#
# The in-place counterpart to overnight-git-env.sh. In-place sessions
# (`/dev-overnight` without --worktree) must NOT get the policy shim: the shim
# denies any op whose effective directory is under the main root and outside a
# worktree (scripts/overnight-git/git-policy-shim:179-182), which in in-place
# mode is every git command the actor will ever run. Wiring it would brick the
# session outright.
#
# But the actor marker is a SEPARATE concern and must survive. The shim needs
# BOTH CLAUDE_OVERNIGHT_ACTOR=1 and CLAUDE_OVERNIGHT_MAIN_ROOT to activate
# (git-policy-shim:53); the keystone needs only the marker
# (hooks/git-keystone/reference-transaction:42). Exporting the marker WITHOUT
# main-root therefore leaves the shim inert and the keystone armed — and the
# keystone is the only thing still protecting the protected branch once the
# user has opted out of a worktree boundary.
#
# WHY A FILE AND NOT A ONE-LINE INSTRUCTION: each Bash tool call is a fresh
# shell. An `export` performed in one call does not reach the next, so an actor
# told once to "export CLAUDE_OVERNIGHT_ACTOR=1" runs unmarked for every
# subsequent git process and the keystone silently stops applying. Sourcing this
# file at the start of each command makes the marker reproducible instead of
# depending on shell-state that does not persist.
#
# Usage (source it):  source overnight-inplace-env.sh --main-root <main_root>
# Output (when not sourced): prints the export lines to stdout.

# Do NOT `set -e` — this file is meant to be SOURCED, and it would leak into the
# actor's shell. Use BASH_SOURCE[0]: $0 is the SOURCING shell when sourced.
_OIE_SELF="${BASH_SOURCE[0]:-$0}"

MAIN_ROOT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --main-root) MAIN_ROOT="$2"; shift 2 ;;
    --worktree)  shift 2 ;;   # accepted and ignored: there is no worktree here
    *) shift ;;
  esac
done

# CLAUDE_OVERNIGHT_MAIN_ROOT is deliberately NOT exported. Setting it is what
# arms the policy shim, and an armed shim denies every in-place git op. It is
# accepted as an argument only so callers can pass the same flags they pass to
# overnight-git-env.sh; the value is used for nothing but the notice below.
export CLAUDE_OVERNIGHT_ACTOR=1
unset CLAUDE_OVERNIGHT_MAIN_ROOT
unset CLAUDE_OVERNIGHT_WORKTREE

if [[ "${_OIE_SELF}" == "${0}" ]]; then
  # Executed rather than sourced: emit the lines a caller can eval.
  echo "export CLAUDE_OVERNIGHT_ACTOR=1"
  echo "unset CLAUDE_OVERNIGHT_MAIN_ROOT"
  echo "unset CLAUDE_OVERNIGHT_WORKTREE"
  echo "# OVERNIGHT_INPLACE_ENV_MARKER_ONLY=1"
  echo "# OVERNIGHT_INPLACE_ENV_MAIN_ROOT=${MAIN_ROOT}"
fi
