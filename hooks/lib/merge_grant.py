#!/usr/bin/env python3
"""merge_grant.py -- the one validator of the merge-analyst grant.

The merge-analyst writes its grant with the Write tool at

    <state dir>/agentic-commit/merge-analyst/<REPO_HASH>/<SESSION_ID>/<REQUEST_ID>.json

and /merge Step 3 reads its verdict and risks verbatim. The grant is checked
once, on the producer's own tool call: hooks/posttool-allowlist-consume.py runs
`fault()` at the PostToolUse of that Write, removes a faulty grant (as /merge
Step 3 did before) and returns the fault to the merge-analyst, which writes the
grant again before it stops. (Experiment E11: the
privilege guard's merge-grant check sat behind CLAUDE_MERGE_COMMAND_ACTIVE=1 in
the hook's own environment, which the compliant /merge never produces --
hooks/merge.sh exports it only to its own subprocess, which no hook sees.)

Each check binds the grant to what its path and the live repository say,
never to the grant's own claims: the request id and session id are path
segments, the repository hash is recomputed from the recorded root, and the
two tips are read from git.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_state_dir import harness_state_dir  # noqa: E402

VERDICTS = ("approved", "blocked")


def grant_root() -> str:
    return os.path.join(harness_state_dir(), "agentic-commit", "merge-analyst")


def is_grant_path(path: str) -> bool:
    """True iff `path` is <grant root>/<hash>/<session>/<request>.json."""
    if not isinstance(path, str) or not path.endswith(".json"):
        return False
    rel = os.path.relpath(os.path.abspath(path), grant_root())
    parts = rel.split(os.sep)
    return len(parts) == 3 and not rel.startswith("..")


def _git(cwd: str, *args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", cwd] + list(args),
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (done.stdout or "").strip() if done.returncode == 0 else ""


def fault(path: str) -> str:
    """Why the grant at `path` is not a valid merge-analyst grant, or ''."""
    repo_hash, session_id, name = os.path.relpath(
        os.path.abspath(path), grant_root()).split(os.sep)
    request_id = name[:-len(".json")]
    try:
        grant = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        return f"the grant is not valid JSON ({exc})"
    if not isinstance(grant, dict):
        return "the grant is not a JSON object"
    for field, expected in (("nonce", request_id), ("session_id", session_id)):
        if grant.get(field) != expected:
            return f"`{field}` is {grant.get(field)!r}; the grant's path says {expected!r}"
    repo_root = grant.get("repo_root")
    if not isinstance(repo_root, str) or not repo_root:
        return "`repo_root` is missing"
    if hashlib.sha256(os.path.realpath(repo_root).encode()).hexdigest()[:16] != repo_hash:
        return f"`repo_root` {repo_root!r} does not hash to the path's REPO_HASH {repo_hash!r}"
    toplevel = _git(repo_root, "rev-parse", "--show-toplevel")
    if not toplevel or os.path.realpath(toplevel) != os.path.realpath(repo_root):
        return f"`repo_root` {repo_root!r} is not the top level of a git repository"
    ref, default_branch = grant.get("branch"), grant.get("default_branch")
    if not isinstance(ref, str) or not ref or not isinstance(default_branch, str) or not default_branch:
        return "`branch` (the resolved merge source) or `default_branch` is missing"
    live_source = _git(repo_root, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
    if not live_source or grant.get("source_tip") != live_source:
        return f"`source_tip` {grant.get('source_tip')!r} is not {ref!r}'s live tip {live_source!r}"
    live_default = _git(repo_root, "rev-parse", "--verify", "--quiet",
                        f"refs/heads/{default_branch}^{{commit}}")
    if not live_default or grant.get("default_tip") != live_default:
        return (f"`default_tip` {grant.get('default_tip')!r} is not {default_branch!r}'s "
                f"live tip {live_default!r}")
    if grant.get("verdict") not in VERDICTS:
        return f"`verdict` is {grant.get('verdict')!r}, not one of {VERDICTS}"
    if not isinstance(grant.get("risks"), list):
        return "`risks` is not a JSON array"
    try:
        expires = datetime.fromisoformat(str(grant.get("expires_at")).replace("Z", "+00:00"))
    except ValueError:
        return f"`expires_at` {grant.get('expires_at')!r} is not an ISO-8601 time"
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        return f"`expires_at` {grant.get('expires_at')!r} is naive or already past"
    return ""
