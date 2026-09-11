"""Regression test for AC-L22 (task 20260808-035658-lanel, Must-Have #10).

commands/dev-overnight.md:1561 previously called a bare, unqualified
`commit.sh` via PATH lookup; scripts/commit.sh did not exist anywhere on this
branch, producing a reproducible exit 127. This test proves the invocation is
now REACHABLE (never exits 127), bounded strictly to reachability -- it does
NOT assert scripts/commit.sh performs a full CAS/content-bound-ledger commit
(that redesign is explicitly out of this Must-Have's scope).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dev_lifecycle_fixtures import git_commit_all, init_git_repo  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMIT_SH = REPO_ROOT / "scripts" / "commit.sh"


def test_commit_sh_exists_and_is_executable():
    assert COMMIT_SH.is_file(), "scripts/commit.sh must exist -- this is the reachability fix itself"
    import os

    assert os.access(COMMIT_SH, os.X_OK), "scripts/commit.sh must be executable"


def test_commit_sh_missing_argument_is_not_127():
    proc = subprocess.run(["bash", str(COMMIT_SH)], capture_output=True, text=True)
    assert proc.returncode != 127
    assert proc.returncode == 1


def test_commit_sh_clean_repo_exits_zero_not_127(tmp_path):
    repo = tmp_path / "clean-repo"
    init_git_repo(repo)
    git_commit_all(repo, "chore: initial")

    proc = subprocess.run(["bash", str(COMMIT_SH), "chore(overnight): end-of-cycle commit", str(repo)],
                           capture_output=True, text=True)
    assert proc.returncode != 127
    assert proc.returncode == 0
    assert "nothing to commit" in proc.stdout


def test_commit_sh_dirty_repo_fails_closed_not_127(tmp_path):
    """The bounded fix: reachability is proven (no exit 127); a dirty repo
    fails CLOSED with a clear non-127 exit rather than self-authorizing a
    real HEAD commit outside the /commit grant/CAS security model."""
    repo = tmp_path / "dirty-repo"
    init_git_repo(repo)
    git_commit_all(repo, "chore: initial")
    (repo / "new-file.txt").write_text("uncommitted change\n", encoding="utf-8")

    proc = subprocess.run(["bash", str(COMMIT_SH), "chore(overnight): end-of-cycle commit", str(repo)],
                           capture_output=True, text=True)
    assert proc.returncode != 127
    assert proc.returncode != 0
    assert "cannot self-authorize" in proc.stderr

    # It must NOT have created a real commit outside the authorized channel.
    log = subprocess.run(["git", "-C", str(repo), "log", "--oneline"], capture_output=True, text=True).stdout
    assert len(log.strip().splitlines()) == 1  # still just the initial commit


def test_dev_overnight_step19_no_longer_references_bare_unqualified_commit_sh():
    """The actual defect: commands/dev-overnight.md:1561 called bare
    `commit.sh` (PATH lookup) with no discoverable script on this branch,
    producing a reproducible exit 127. This test extracts the LITERAL
    documented invocation out of commands/dev-overnight.md and subprocess-
    executes it (from the project root, with a minimal PATH that deliberately
    excludes scripts/ so a bare `commit.sh` could not resolve via PATH
    lookup), then asserts the exit code is never 127. A prior version of this
    test only checked that the substring 'commit.sh' appeared in the doc and
    that scripts/commit.sh existed on disk -- both were true before AND after
    the doc's invocation text was actually fixed, so it stayed green while
    the real defect remained unfixed. This version fails if that regresses."""
    dev_overnight_md = (REPO_ROOT / "commands" / "dev-overnight.md").read_text(encoding="utf-8")

    match = re.search(r"Call `([^`]*?commit\.sh[^`]*?)`", dev_overnight_md)
    assert match, "commands/dev-overnight.md must document a `Call `...commit.sh...`` Step-19 invocation"
    invocation = match.group(1)

    minimal_path = "/usr/bin:/bin"  # deliberately excludes scripts/ -- only a resolvable path works
    proc = subprocess.run(
        ["bash", "-c", invocation],
        cwd=REPO_ROOT,
        env={"PATH": minimal_path},
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 127, (
        f"documented Step-19 invocation {invocation!r} exited 127 (command not found) "
        f"when executed literally from the project root; stderr={proc.stderr!r}"
    )
