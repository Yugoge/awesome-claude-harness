#!/usr/bin/env python3
"""Write the push-gate token for a commit just landed: the token's one writer.

Run after its own commit by both of the token's callers: changelog-analyst under
/commit (Phase 10, and the precommitted-recovery path) and the cleaner under
/clean. hooks/push.sh is the token's one decider: /push passes only while some
token's commit_sha is an ancestor of HEAD.

    python3 ~/.claude/scripts/write-push-gate-token.py \\
        --repo-root <GIT_ROOT> --branch <BRANCH> --commit <COMMIT_SHA>

The path is resolved here, never by a caller:

    <state dir>/agentic-commit/push/<sha256(realpath(repo root))[:16]>/
        <sha256(session id)[:16]>/<branch with / replaced by __>.json

<state dir> is harness_state_dir() (hooks/lib/harness_state_dir.py), the
directory push.sh reads. The session id is CLAUDE_CODE_SESSION_ID, else
CLAUDE_SESSION_ID, else `unknown`; only its digest becomes a path segment (a
raw environment value could carry `/` or `..`), while the token's
`session_id` field keeps the raw value. The session segment keeps two sessions
on one branch from contending for a single slot.

Checks, all before the write, so a token that would not authorize /push is
never written:
  - the commit is a commit object and is live HEAD at the repository root
    (otherwise HEAD moved since the caller's commit: push_gate_race);
  - a token already at the path that names another session_id is never
    overwritten (push_gate_collision).
After the write HEAD is read once more; a HEAD that moved during the write is
reported as push_gate_race, as the token may no longer name HEAD.

The write is atomic (temp file + rename in the token directory), so push.sh
never reads a partial token. The command line carries no token content and no
token path. `--print-path` prints the path a write would use and writes nothing:
push-gate reconciliation (agents/changelog-analyst.md) reads the slot through it,
so the path rule lives here only.

Exit codes:
  0  token written; its path is printed on stdout
  2  usage error, or the repository root cannot be resolved
  3  push_gate_race: the commit is not a commit object, is not live HEAD, or
     HEAD moved during the write
  4  push_gate_collision: another session's token holds the path; not written
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Same cross-directory import shape as scripts/write-commit-grant.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks" / "lib"))
from harness_state_dir import harness_state_dir  # noqa: E402

EXIT_RACE = 3
EXIT_COLLISION = 4


def _git(repo_root: str, *args: str) -> str:
    """`git -C repo_root <args>` stdout stripped, or '' on any failure."""
    try:
        result = subprocess.run(["git", "-C", repo_root] + list(args),
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (result.stdout or "").strip() if result.returncode == 0 else ""


def session_id() -> str:
    return (os.environ.get("CLAUDE_CODE_SESSION_ID")
            or os.environ.get("CLAUDE_SESSION_ID") or "unknown")


def token_path(repo_root: str, branch: str, sid: str) -> Path:
    repo_hash = hashlib.sha256(os.path.realpath(repo_root).encode()).hexdigest()[:16]
    sid_digest = hashlib.sha256(sid.encode()).hexdigest()[:16]
    return (Path(harness_state_dir()) / "agentic-commit" / "push" / repo_hash
            / sid_digest / (branch.replace("/", "__") + ".json"))


def _is_live_head(repo_root: str, commit: str) -> bool:
    return (bool(_git(repo_root, "cat-file", "-t", commit + "^{commit}"))
            and _git(repo_root, "rev-parse", "HEAD") == commit)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="write-push-gate-token.py",
        description="Write the push-gate token for a commit just landed.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--print-path", action="store_true",
                        help="print the token path and write nothing")
    args = parser.parse_args(argv)

    repo_root = _git(args.repo_root, "rev-parse", "--show-toplevel")
    if not repo_root or not args.branch.strip() or not args.commit.strip():
        print(f"push-gate token not written: {args.repo_root!r} is not a git "
              "repository, or --branch/--commit is empty", file=sys.stderr)
        return 2
    commit = args.commit.strip()
    if args.print_path:
        print(str(token_path(repo_root, args.branch, session_id())))
        return 0
    if not _is_live_head(repo_root, commit):
        print(f"push_gate_race: {commit!r} is not live HEAD "
              f"({_git(repo_root, 'rev-parse', 'HEAD')!r}) of {repo_root!r}; "
              "no token written", file=sys.stderr)
        return EXIT_RACE

    sid = session_id()
    path = token_path(repo_root, args.branch, sid)
    try:
        existing = json.loads(path.read_text())
    except (OSError, ValueError):
        existing = None
    if isinstance(existing, dict) and existing.get("session_id") not in (None, sid):
        print(f"push_gate_collision: {path} holds session {existing.get('session_id')!r}'s "
              f"token, not {sid!r}'s; not overwritten", file=sys.stderr)
        return EXIT_COLLISION

    token = {"commit_sha": commit, "branch": args.branch, "repo_root": repo_root,
             "session_id": sid}
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".token-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as fp:
            json.dump(token, fp)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        print(f"push-gate token not written: {exc}", file=sys.stderr)
        return 2
    if _git(repo_root, "rev-parse", "HEAD") != commit:
        print(f"push_gate_race: HEAD moved while {path} was written", file=sys.stderr)
        return EXIT_RACE
    print(str(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
