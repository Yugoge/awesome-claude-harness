#!/usr/bin/env python3
"""/push Steps 0 and 2: the push remote and the pre-push snapshot, in one call.

    python3 scripts/steps/push-snapshot.py [--remote <name>]

Run from the repository to push. Prints one `KEY=value` line per fact (the same names as the
placeholders of the push-analyst dispatch and of the execute-push.py call):

BRANCH           `git rev-parse --abbrev-ref HEAD`: `HEAD` on a detached HEAD.
PRE_HEAD         `git rev-parse HEAD`.
RESOLVED_REMOTE  the remote the push targets: `--remote` when given, else DEFAULT_REMOTE.
DEFAULT_REMOTE   what a bare `/push` targets: `fork` when that remote exists locally, else `origin`.
REMOTE_URL       `git remote get-url` of RESOLVED_REMOTE; `unknown` when that remote does not exist
                 (hooks/push.sh refuses it later: exit 1, "remote '<name>' not found").
REQUEST_ID       a fresh 32-hex nonce: it names the push-analyst grant and binds the whole push.
SESSION_ID       $CLAUDE_SESSION_ID, else $CLAUDE_CODE_SESSION_ID; empty when neither is set.
REPO_ROOT        the real path of the git top level.
REPO_HASH        sha256(REPO_ROOT)[:16], the key hooks/push.sh and scripts/execute-push.py use for the
                 repository's state directories.

An empty SESSION_ID and BRANCH=HEAD are facts for the command to refuse on, not failures of this
script. Exit codes:
  0  the lines above were printed
  1  the working directory is not inside a git work tree; nothing is printed
  2  usage error
"""
from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import subprocess
import sys


def git(*args: str) -> tuple[int, str]:
    """(exit status, stdout without its trailing newlines): the value of a shell `$(git ...)`, which
    keeps whatever git printed even when it failed."""
    proc = subprocess.run(["git", *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True, errors="replace")
    return proc.returncode, proc.stdout.rstrip("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="push-snapshot.py", description=__doc__.split("\n")[0])
    parser.add_argument("--remote", default="", help="the remote typed after /push (default: none)")
    args = parser.parse_args(argv)

    code, top = git("rev-parse", "--show-toplevel")
    if code != 0 or not top:
        print("push-snapshot: not inside a git work tree", file=sys.stderr)
        return 1
    repo_root = os.path.realpath(top)

    default_remote = "fork" if git("remote", "get-url", "fork")[0] == 0 else "origin"
    resolved = args.remote or default_remote
    url_code, url = git("remote", "get-url", resolved)

    facts = [
        ("BRANCH", git("rev-parse", "--abbrev-ref", "HEAD")[1]),
        ("PRE_HEAD", git("rev-parse", "HEAD")[1]),
        ("RESOLVED_REMOTE", resolved),
        ("DEFAULT_REMOTE", default_remote),
        ("REMOTE_URL", url if url_code == 0 else "unknown"),
        ("REQUEST_ID", secrets.token_hex(16)),
        ("SESSION_ID", os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""),
        ("REPO_ROOT", repo_root),
        ("REPO_HASH", hashlib.sha256(repo_root.encode()).hexdigest()[:16]),
    ]
    for key, value in facts:
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
