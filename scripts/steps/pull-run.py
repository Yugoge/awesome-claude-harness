#!/usr/bin/env python3
"""Steps 0-4 of /pull and its Graphify update: run the pull, read what changed, decide the exit phase.

    pull-run.py run
    pull-run.py graphify

Run from the repository being pulled into (the session's working directory).

run       reads HEAD and the branch, runs <HARNESS_ROOT>/hooks/pull.sh with this call's stdin, stdout and
          stderr (its output reaches the session as it always did, in order, before anything below), reads
          HEAD again whatever the exit code, and prints a marker line `--- pull-run ---` followed by
          KEY=value lines:
          PRE_PULL_HEAD   HEAD before the pull ("" in a repository with no commit).
          POST_PULL_HEAD  HEAD after it (pull.sh may move HEAD in a rebase that then stops, or after a rebase
                          that finished and a stash pop that failed).
          BRANCH          `git rev-parse --abbrev-ref HEAD` ("HEAD" when detached).
          PULL_EXIT_CODE  pull.sh's exit code (127 when bash cannot find the file).
          REBASE_STATE    yes when a rebase-merge or rebase-apply directory exists (worktree-aware paths).
          PULL_EXIT_PHASE success            exit code 0;
                          rebase_conflict    exit code not 0 and a rebase in progress, or no rebase and HEAD
                                             unchanged (a failure before the rebase, classified the same way);
                          stash_restoration_failed  exit code not 0, no rebase in progress, HEAD moved (the
                                             rebase finished, the stash pop failed).
          ACTION          no_change  exit code 0 and HEAD unchanged (the pull did nothing, or was cancelled):
                                     skip the pull-analyst;
                          analyze    HEAD moved and no rebase is stopped (phase success, or
                                     stash_restoration_failed): dispatch the pull-analyst;
                          stop       phase rebase_conflict: no pull-analyst.
          The exit status is 0 whatever pull.sh did: a stopped pull is a fact printed above, not a failure
          of this script. It is 2 only for wrong arguments.
graphify  the advisory Graphify cache update after a pull: `graphify-maintain.py update` from the harness
          home ($CLAUDE_HOME, else ~/.claude), with that home's venv/bin first on PATH when it exists (the
          graphify CLI is installed there). It never fails: the exit status is 0 and a failure is a line on
          stderr.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parents[2]
MARKER = "--- pull-run ---"


def git_out(*args: str) -> str:
    """The first line git prints on stdout, or "" when git fails (a failed read is an empty fact)."""
    proc = subprocess.run(["git", *args], stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace")
    return proc.stdout.strip().split("\n")[0] if proc.returncode == 0 else ""


def rebase_in_progress() -> bool:
    """A rebase-merge or rebase-apply directory exists. `--git-path` follows a linked worktree's own gitdir;
    when git cannot answer, the plain `.git/` spelling is tried, as the prompt did."""
    for name in ("rebase-merge", "rebase-apply"):
        path = git_out("rev-parse", "--git-path", name) or f".git/{name}"
        if os.path.isdir(path):
            return True
    return False


def classify(exit_code: int, pre: str, post: str, rebasing: bool) -> tuple[str, str]:
    """(PULL_EXIT_PHASE, ACTION)."""
    if exit_code == 0:
        return ("success", "no_change" if pre == post else "analyze")
    if rebasing:
        return ("rebase_conflict", "stop")
    if pre != post:
        return ("stash_restoration_failed", "analyze")
    return ("rebase_conflict", "stop")


def run_pull() -> int:
    pre = git_out("rev-parse", "HEAD")
    branch = git_out("rev-parse", "--abbrev-ref", "HEAD")
    sys.stdout.flush()
    sys.stderr.flush()
    code = subprocess.run(["bash", str(HARNESS_ROOT / "hooks" / "pull.sh")]).returncode
    post = git_out("rev-parse", "HEAD")
    rebasing = rebase_in_progress()
    phase, action = classify(code, pre, post, rebasing)
    facts = [("PRE_PULL_HEAD", pre), ("POST_PULL_HEAD", post), ("BRANCH", branch), ("PULL_EXIT_CODE", str(code)),
             ("REBASE_STATE", "yes" if rebasing else "no"), ("PULL_EXIT_PHASE", phase), ("ACTION", action)]
    print(MARKER)
    for key, value in facts:
        print(f"{key}={value}")
    return 0


def graphify_update() -> int:
    home = Path(os.environ.get("CLAUDE_HOME") or Path.home() / ".claude")
    env = dict(os.environ)
    venv = home / "venv"
    if (venv / "bin").is_dir():
        env["PATH"] = f"{venv / 'bin'}{os.pathsep}{env.get('PATH', '')}"
        env["VIRTUAL_ENV"] = str(venv)
        env.pop("PYTHONHOME", None)
    try:
        subprocess.run(["python3", str(home / "scripts" / "graphify-maintain.py"), "update"], env=env,
                       stdin=subprocess.DEVNULL, check=False)
    except OSError as exc:
        print(f"pull-run graphify: {exc}", file=sys.stderr)
    return 0


def main(argv: list[str]) -> int:
    if argv == ["run"]:
        return run_pull()
    if argv == ["graphify"]:
        return graphify_update()
    print("usage: pull-run.py run | graphify", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
