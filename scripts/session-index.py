#!/usr/bin/env python3
"""CLI over scripts/lib/session_index.py: per-session private git index.

Subcommands (all take --git-root):

  init         Seed this session's private index from HEAD. Prints
               `export GIT_INDEX_FILE=...` for `eval`. Run once per commit run,
               and again per bulk group, because HEAD moves after each commit.
  export       Verify the private index and that HEAD has not moved since
               seeding. Prints the same export line. This is the pre-commit gate:
               run it immediately before `git commit`.
  sync-shared  After a commit, bring the shared index's entries for the committed
               paths up to the new HEAD (see sync_shared_after_commit). Prints a
               JSON report.

Refusals print `SESSION-INDEX REFUSED reason=<slug>: <detail>` on stderr and exit 3.
"""

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import session_index  # noqa: E402

REFUSED = 3


def _refuse(exc):
    sys.stderr.write("SESSION-INDEX REFUSED reason=%s: %s\n" % (exc.reason, exc.detail))
    return REFUSED


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=("init", "export", "sync-shared"))
    ap.add_argument("--git-root", required=True)
    args = ap.parse_args(argv)
    git_root = os.path.realpath(args.git_root)
    try:
        if args.command == "init":
            index = session_index.init(git_root)
            print("export GIT_INDEX_FILE=%s" % shlex.quote(index))
            return 0
        if args.command == "export":
            session_index.commit_gate(git_root)
            index = session_index.index_path(git_root)
            print("export GIT_INDEX_FILE=%s" % shlex.quote(index))
            return 0
        report = session_index.sync_shared_after_commit(git_root)
        sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
        return 0
    except session_index.SessionIndexError as exc:
        return _refuse(exc)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
