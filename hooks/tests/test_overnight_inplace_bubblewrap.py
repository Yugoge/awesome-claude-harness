#!/usr/bin/env python3
"""An in-place /dev-overnight launch needs bubblewrap (P2 R13's bwrap experiment).

Replayed in a bwrap-less in-place toy session, every removal of the git
keystone's core.hooksPath (`git config --unset`, `git -C <repo> config
--unset-all`, pointing it at /dev/null, an Edit of .git/config), as the main
agent and as a subagent, passed every hook settings.json registers and removed
the key. So the launcher refuses an in-place launch where bubblewrap cannot
run: it names bubblewrap and writes nothing (no state, no keystone). Where it
runs (here a stand-in that runs the command it is given), the launch goes on.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parents[2] / "scripts" / "create-overnight-state.sh"
ENV = {k: v for k, v in os.environ.items() if k != "CLAUDE_OVERNIGHT_FORCE_NO_BWRAP"}
ENV.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
           GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@example.invalid")


def _git(*args, cwd):
    assert subprocess.run(["git", *args], cwd=cwd, env=ENV, capture_output=True).returncode == 0, args


@pytest.fixture
def toy(tmp_path):
    """A product checkout on a working branch, origin/HEAD naming the protected one."""
    repo = tmp_path / "toy"
    repo.mkdir()
    _git("init", "-q", "-b", "master", cwd=repo)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=repo)
    _git("clone", "-q", "--bare", str(repo), str(tmp_path / "origin.git"), cwd=tmp_path)
    for args in (("remote", "add", "origin", str(tmp_path / "origin.git")), ("fetch", "-q", "origin"),
                 ("remote", "set-head", "origin", "master"), ("checkout", "-q", "-b", "night-work")):
        _git(*args, cwd=repo)
    return repo


def _bwrap(tmp_path: Path, body: str) -> str:
    """A PATH whose first entry holds a bwrap with ``body``."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "bwrap").write_text("#!/bin/sh\n" + body)
    (bin_dir / "bwrap").chmod(0o755)
    return f"{bin_dir}:{ENV.get('PATH', '/usr/bin:/bin')}"


def _launch(repo: Path, **env):
    return subprocess.run(["bash", str(LAUNCHER), "--end-time", "2h", "--session-id", "s-bwrap",
                           "--project-dir", str(repo)], cwd=repo, capture_output=True, text=True,
                          timeout=300, env={**ENV, **env})


def _refused(result, repo: Path) -> bool:
    keystone = subprocess.run(["git", "config", "--get", "core.hooksPath"], cwd=repo, env=ENV,
                              capture_output=True, text=True).stdout.strip()
    return (result.returncode == 1 and "bubblewrap" in result.stderr
            and "--worktree" in result.stderr and not (repo / ".claude").exists() and not keystone)


def test_no_bubblewrap_refuses_the_in_place_launch_and_writes_nothing(toy):
    assert _refused(_launch(toy, CLAUDE_OVERNIGHT_FORCE_NO_BWRAP="1"), toy)


def test_a_bubblewrap_that_cannot_run_refuses_too(toy, tmp_path):
    assert _refused(_launch(toy, PATH=_bwrap(tmp_path, "exit 1\n")), toy)


def test_with_bubblewrap_the_in_place_launch_goes_on(toy, tmp_path):
    stand_in = 'while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done\n[ "$#" -gt 0 ] && shift\nexec "$@"\n'
    result = _launch(toy, PATH=_bwrap(tmp_path, stand_in))
    assert result.returncode == 0, result.stderr
    assert '"isolation_kind": "in_place"' in (toy / ".claude" / "overnight-state-s-bwrap.json").read_text()
