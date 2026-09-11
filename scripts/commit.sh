#!/usr/bin/env bash
# Description: Discoverable canonical entrypoint for commands/dev-overnight.md's
#              Step 19 end-of-cycle commit call. Bounded reachability fix only
#              (AC-L22 / Must-Have #10, task 20260808-035658-lanel) -- this is
#              NOT a CAS/content-bound-ledger redesign.
# Usage: commit.sh <commit-message> [repo-root]
# Exit codes:
#   0  nothing to commit (repo already clean) -- a legitimate no-op
#   1  bad usage (missing message argument)
#   3  repo is dirty but this script cannot self-authorize a real HEAD commit
#      (see rationale below) -- the caller (dev-overnight.md Step 19) already
#      treats ANY non-zero exit as "log the failure and continue"; refs/
#      checkpoints/* snapshots remain intact and the operator can promote
#      them manually via /commit.
#
# Root-cause reference: docs/dev/ticket-20260808-035658-lanel.md Must-Have #10
# (objection 1). commands/dev-overnight.md:1561 previously called a bare,
# unqualified `commit.sh` via PATH lookup, which did not exist anywhere on
# this branch -- a reproducible exit 127. This script makes that invocation
# REACHABLE.
#
# Why this script does not itself land a real HEAD commit when dirty: a real
# commit requires the SAME commit-grant/CAS authorization /commit's Step 5-6
# mints (an interactive session id, a QA-reviewed plan, a single-use grant
# bound to repo/branch/HEAD) or the human-only /commit --bulk sentinel.
# agents/changelog-analyst.md:45 and hooks/pretool-bash-safety.sh explicitly
# forbid any script from self-minting that sentinel outside human-invoked
# `/commit --bulk`. A bounded reachability fix must NOT re-implement or
# bypass that security model (No Band-Aid Rule / Must-Have #10's own bounded-
# scope clause) -- the full CAS/content-bound-ledger design referenced in
# dev-overnight.md's prose is explicitly OUT of this Must-Have's scope. Exit
# 3 with a clear message is the honest, safe outcome; refs/checkpoints/*
# (hooks/lib/checkpoint-core.sh) already preserves the work either way.

set -euo pipefail

MESSAGE="${1:?Usage: commit.sh <commit-message> [repo-root]}"
REPO_ROOT="${2:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

if [[ -z "$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null)" ]]; then
  echo "commit.sh: nothing to commit in $REPO_ROOT."
  exit 0
fi

echo "commit.sh: $REPO_ROOT has uncommitted changes, but this script cannot self-authorize a real HEAD commit." >&2
echo "commit.sh: a real commit requires the commit-grant/CAS authorization only /commit (Step 5-6) or a human-invoked /commit --bulk can mint." >&2
echo "commit.sh: message was: ${MESSAGE}" >&2
echo "commit.sh: refs/checkpoints/* snapshots remain intact -- promote manually via /commit when ready (see docs/reference/checkpoint-mechanism.md)." >&2
exit 3
