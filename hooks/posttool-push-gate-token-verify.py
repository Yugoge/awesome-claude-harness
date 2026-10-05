#!/usr/bin/env python3
"""
PostToolUse Hook: write-time validation of the push-gate token's commit_sha.

WHY (root cause, task 20261001-161041-r15). agents/changelog-analyst.md Phase 10
writes the push-gate token (/tmp/agentic-commit/push/<repo_hash>/<sid_digest>/
<branch>.json) via the Write tool, gated only by three PRE-write/POST-write checks
the LLM agent itself must execute in prose (agents/changelog-analyst.md:1221-1225,
identically :555-569). Nothing independently re-verifies the agent actually ran them
correctly. The only mechanized commit_sha comparison anywhere in hooks/*.py or
hooks/*.sh is hooks/push.sh:206-238's ancestor scan, which runs at /push time --
potentially long after the write. This hook closes that gap by re-deriving live HEAD
at the token's own repo_root immediately after the Write and comparing it to the
token's commit_sha, mechanizing the exact invariant agents/changelog-analyst.md
already states in prose (it does not invent a new rule).

This hook is a READ-ONLY validator: it never writes the push-gate token itself (that
redesign is explicitly deferred -- docs/reference/push-gate-reconciliation-decision.md
Section 7) and it does not touch the reconciliation mechanism (decided and closed,
same document). On mismatch it quarantines (renames) the token so hooks/push.sh's
glob can never read it as a candidate, and prints a clear stderr message -- it cannot
block the Write itself (PostToolUse fires after the tool already returned).

Hook type: PostToolUse (matcher: Write)
Exit codes: 0 = pass (non-matching path, unreadable/unparseable token, or commit_sha
            correctly matches live HEAD); 1 = mismatch detected and token quarantined
"""

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.harness_state_dir import harness_state_dir  # noqa: E402

# Matches both token layouts hooks/push.sh:212-215 scans: the legacy depth-1 path
# (<repo_hash>/<branch>.json) and the session-scoped depth-2 path this repo's current
# Phase 10 procedure writes (<repo_hash>/<sid_digest>/<branch>.json). repo_hash and
# sid_digest are both sha256(...)[:16] per agents/changelog-analyst.md:1217,1216 --
# always 16 lowercase hex chars.
_TOKEN_PATH_RE = re.compile(
    '^' + re.escape(harness_state_dir())
    + r'/agentic-commit/push/[0-9a-f]{16}/(?:[0-9a-f]{16}/)?[^/]+\.json$'
)


def _get_file_path():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return ''
    tool_input = data.get('tool_input', {}) if isinstance(data, dict) else {}
    path = tool_input.get('file_path', '') if isinstance(tool_input, dict) else ''
    return path if isinstance(path, str) else ''


def _git_head(repo_root):
    """Live HEAD at repo_root, or None if it cannot be resolved."""
    try:
        result = subprocess.run(
            ['git', '-C', repo_root, 'rev-parse', 'HEAD'],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _commit_exists(repo_root, commit_sha):
    try:
        result = subprocess.run(
            ['git', '-C', repo_root, 'cat-file', '-e', commit_sha + '^{commit}'],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return False
    return result.returncode == 0


def _quarantine(path):
    """Rename the token out of hooks/push.sh's scan path (Should-Have: survives for
    forensic inspection, per BA spec, rather than a hard delete)."""
    rejected = path + '.rejected'
    try:
        os.replace(path, rejected)
        return rejected
    except OSError:
        try:
            os.remove(path)
        except OSError:
            pass
        return None


def main():
    path = _get_file_path()
    if not path or not _TOKEN_PATH_RE.match(path):
        sys.exit(0)

    # The token was just written by the Write tool; if it cannot be read/parsed here,
    # there is nothing to compare. Fail open -- hooks/push.sh's own JSON parse
    # (hooks/push.sh:219-227) independently skips an unparseable candidate at /push
    # time, so this is not a new hole, and this hook must never be the thing that
    # performs or replaces the Write.
    try:
        with open(path, 'r') as f:
            token = json.load(f)
    except Exception:
        sys.exit(0)

    if not isinstance(token, dict):
        sys.exit(0)
    commit_sha = token.get('commit_sha')
    repo_root = token.get('repo_root')
    if not isinstance(commit_sha, str) or not commit_sha \
            or not isinstance(repo_root, str) or not repo_root:
        sys.exit(0)

    head = _git_head(repo_root)
    if head is None:
        # repo_root unresolvable as a git repo from here -- nothing to validate
        # against. Fail open, same posture as the unreadable-token case above.
        sys.exit(0)

    if commit_sha == head and _commit_exists(repo_root, commit_sha):
        sys.exit(0)

    reason = (
        'does not resolve to an existing commit object'
        if not _commit_exists(repo_root, commit_sha)
        else 'does not equal live HEAD'
    )
    quarantined_to = _quarantine(path)
    # Always name BOTH expected HEAD and the token's actual commit_sha (AC3's
    # Must-Have bullet), regardless of which specific reason tripped -- a reader
    # debugging a mismatch needs both values either way.
    print(
        f'[push-gate-token-verify] BLOCKED: push-gate token at {path!r} has '
        f'commit_sha={commit_sha!r} which {reason}; live HEAD at {repo_root!r} '
        f'is {head!r}. Token quarantined'
        + (f' to {quarantined_to!r}' if quarantined_to else ' (removed)')
        + ' so hooks/push.sh can never read it as a candidate. '
        'This does not affect the PRE-write/POST-write checks '
        'agents/changelog-analyst.md already performs -- it is an independent '
        'backstop witness on top of them.',
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == '__main__':
    main()
