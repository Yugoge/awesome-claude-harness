#!/usr/bin/env python3
"""Steps 1 and 4 of /merge: the pre-merge snapshot and the branch-tip re-read, as KEY=value lines.

    merge-snapshot.py snapshot <ref>
    merge-snapshot.py tips <ref> <default-branch>

Run from the repository being merged into (the session's working directory). Every state below is a
fact for the command to act on, never a failure of this script: stdout carries only KEY=value lines,
one per line, and the exit status is 0 unless the arguments are wrong (2).

snapshot  prints the merge-analyst's dispatch context, in this order:
          RESOLVED_REF   <ref> as given.
          SOURCE_TIP     the commit <ref> resolves to (a tag is peeled), or MISSING. The check is "names a
                         commit object", never a refs/heads/ prefix, so a remote-tracking ref, a tag and a
                         bare hash resolve; an unknown or ambiguous name is MISSING.
          DEFAULT_BRANCH scripts/derive-default-branch.sh's answer.
          DEFAULT_TIP    the commit refs/heads/<DEFAULT_BRANCH> names, or MISSING.
          REQUEST_ID     32 random hex characters: the nonce that keys this analysis' grant.
          SESSION_ID     $CLAUDE_CODE_SESSION_ID ("" when unset).
          REPO_HASH      the first 16 hex characters of the sha256 of REPO_ROOT.
          REPO_ROOT      the realpath of `git rev-parse --show-toplevel` ("" outside a repository, where both
                         tips are MISSING).
tips      prints CURRENT_SOURCE_TIP and CURRENT_DEFAULT_TIP: the two tips read again, MISSING included.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import subprocess
import sys
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parents[2]
MISSING = "MISSING"


def emit(**facts: str) -> None:
    for key, value in facts.items():
        print(f"{key}={value.replace(chr(10), ' ')}")


def git(*args: str) -> tuple[int, str]:
    proc = subprocess.run(["git", *args], stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace")
    return proc.returncode, proc.stdout.strip()


def commit_of(rev: str) -> str:
    """The commit `rev` peels to, else MISSING (--verify makes an ambiguous or unknown name a failure)."""
    code, out = git("rev-parse", "--verify", "--quiet", rev + "^{commit}")
    return out if code == 0 and out else MISSING


def default_branch() -> str:
    proc = subprocess.run(["bash", str(HARNESS_ROOT / "scripts" / "derive-default-branch.sh")],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace")
    return proc.stdout.strip()


def repo_root() -> str:
    code, top = git("rev-parse", "--show-toplevel")
    return os.path.realpath(top) if code == 0 and top else ""


def snapshot(ref: str) -> None:
    branch = default_branch()
    root = repo_root()
    emit(RESOLVED_REF=ref, SOURCE_TIP=commit_of(ref), DEFAULT_BRANCH=branch,
         DEFAULT_TIP=commit_of(f"refs/heads/{branch}"), REQUEST_ID=secrets.token_hex(16),
         SESSION_ID=os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
         REPO_HASH=hashlib.sha256(root.encode()).hexdigest()[:16], REPO_ROOT=root)


def tips(ref: str, branch: str) -> None:
    emit(CURRENT_SOURCE_TIP=commit_of(ref), CURRENT_DEFAULT_TIP=commit_of(f"refs/heads/{branch}"))


def main(argv: list[str]) -> int:
    # The operands are data: a ref that starts with "-" is looked up like any other name.
    if len(argv) == 2 and argv[0] == "snapshot":
        snapshot(argv[1])
    elif len(argv) == 3 and argv[0] == "tips":
        tips(argv[1], argv[2])
    else:
        print("usage: merge-snapshot.py snapshot <ref> | tips <ref> <default-branch>", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
