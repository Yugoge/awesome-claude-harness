"""Regression test for AC-L22 (task 20260808-035658-lanel, Must-Have #10).

commands/dev-overnight.md:1561 previously called a bare, unqualified
`commit.sh` via PATH lookup; scripts/commit.sh did not exist anywhere on this
branch, producing a reproducible exit 127. These tests prove the script is
REACHABLE (never exits 127), bounded strictly to reachability -- they do
NOT assert scripts/commit.sh performs a full CAS/content-bound-ledger commit
(that redesign is explicitly out of this Must-Have's scope).

Step 19 no longer commits at all: the overnight session's work stays in
refs/checkpoints/<branch> until the owner types the post-loop flow, so
commands/dev-overnight.md names no commit.sh (the script stays in scripts/).
"""

from __future__ import annotations

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


def test_dev_overnight_step19_has_no_commit_sh_and_the_owner_lands_the_work():
    """Step 19's per-cycle commit is gone: commands/dev-overnight.md names no
    commit.sh and no `/commit --bulk`, and Step 19 keeps the cycle's work in
    refs/checkpoints/<branch>. The work lands once, after the session, by the
    four commands the owner types: the announcement and the Post-loop flow
    both list /close --auto, /commit --auto, /merge <worktree_branch>
    (isolated modes) and /push in that order, with where each runs; the
    in_place announcement lists the same flow without /merge."""
    text = (REPO_ROOT / "commands" / "dev-overnight.md").read_text(encoding="utf-8")
    assert "commit.sh" not in text
    assert "commit --bulk" not in text
    step19 = text.split("### Step 19:", 1)[1].split("### Step 20:", 1)[0]
    assert "refs/checkpoints/" in step19
    assert "**TIME CHECK**" in step19

    announce = text.split("**Announce completion**:", 1)[1].split("### Post-loop flow", 1)[0]
    flow = text.split("### Post-loop flow", 1)[1].split("\n## ", 1)[0]
    order = ("/close --auto", "/commit --auto", "/merge <worktree_branch>", "/push")
    for part in (announce, flow):
        positions = [part.find(cmd) for cmd in order]
        assert -1 not in positions, (order, positions)
        assert positions == sorted(positions), (order, positions)
    isolated, in_place = announce.split("<If isolation_kind == 'in_place', include instead:>", 1)
    assert "In a session opened at <worktree_path>" in isolated
    assert "in the main checkout" in isolated
    in_place_order = [in_place.find(cmd) for cmd in ("/close --auto", "/commit --auto", "/push")]
    assert -1 not in in_place_order and in_place_order == sorted(in_place_order), in_place_order
    assert "/merge <" not in in_place
    assert "in the main checkout" in flow and "a session opened at `<worktree_path>`" in flow
