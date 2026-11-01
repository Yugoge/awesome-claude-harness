#!/usr/bin/env bash
# Stop Hook: reap every /allow grant the reader rejects at turn end.
# Registered LAST in Stop hooks array so earlier hook failures do not block cleanup.
# Exits 0 always (cleanup is best-effort; never blocks agent stop).
# NOTE: NO `set -e` — a missing grant file is expected and must not error out.
set -u

# Every reap below resolves the state directory and decides through its
# reader's library, so nothing here reads the payload; drain it.
cat >/dev/null

# /do consent and the tool streak are cleared at the next human prompt by
# hooks/prompt-workflow.py (D5: one clearer per fact), never at Stop.

# ── Sentinel-grant reap (task 20260519-211515 R2 / AC2) ──
# At session stop, sweep <state dir>/claude-grants/*.json: unlink every sentinel
# hooks/lib/allowlist.py's reader rejects (expired, malformed, or missing a
# required key). Bounded best-effort; never blocks agent stop. The reaper
# delegates to hooks/lib/allowlist.reap_expired_sentinel_grants().
HOOK_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
python3 -c "
import sys
sys.path.insert(0, '${HOOK_DIR}')
from lib.allowlist import reap_expired_sentinel_grants
print('[stop-cleanup] reaped', reap_expired_sentinel_grants(), 'claude-grants/* sentinel grants', file=sys.stderr)
" 2>/dev/null || true

# ── Bulk-commit sentinel and commit-event pointer reaps ──
# Each reap takes the reading of that file's one decider instead of a rule of
# its own: a bulk-commit sentinel goes when the privilege guard would no longer
# admit an auto-bulk commit on it (hooks/lib/commit_pipeline.py
# bulk_commit_sentinel_live), a commit-event pointer when the PostToolUse
# finalizer's stale reading says no event will finalize it
# (hooks/lib/commit_journal.py reap_stale_pointers).
python3 -c "
import sys
sys.path.insert(0, '${HOOK_DIR}/lib')
import commit_journal, commit_pipeline
print('[stop-cleanup] reaped', commit_pipeline.reap_bulk_commit_sentinels(), 'bulk-commit sentinels,',
      commit_journal.reap_stale_pointers(), 'commit-event pointers', flush=True)
" 2>/dev/null || true

exit 0
