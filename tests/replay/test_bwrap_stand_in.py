"""The replays model a host that has bubblewrap (P2 R13).

An in-place /dev-overnight launch refuses where `bwrap --ro-bind / / -- true` cannot run
(scripts/create-overnight-state.sh), and a CI runner or this container may have no
bubblewrap. So the sandbox puts the framework's stand-in (tests/replay/bin/bwrap) first on
the replayed processes' PATH: it skips bwrap's options up to `--` and runs the rest, and the
launch goes on as the drivers expect.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.replay import sandbox

REPO = Path(__file__).resolve().parents[2]
ENV = {k: v for k, v in os.environ.items() if k != "CLAUDE_OVERNIGHT_FORCE_NO_BWRAP"}
ENV.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
           GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")


@pytest.fixture
def copied(tmp_path) -> Path:
    """The framework as reset() copies it into a sandbox, with its PATH."""
    shutil.copytree(sandbox.HERE, tmp_path / "replay", ignore=sandbox.COPY_IGNORE)
    return tmp_path


@pytest.mark.parametrize("mode", ["ns", "scratch"])
def test_the_stand_in_comes_first_on_the_replayed_processes_path(tmp_path, mode):
    lay = sandbox.layout_for(str(tmp_path / "sb"), mode)
    assert lay.path.split(":")[:2] == [lay.sb + "/replay/bin", lay.harness + "/venv/bin"]


def test_the_stand_in_skips_the_options_and_runs_the_command(copied):
    bwrap = str(copied / "replay" / "bin" / "bwrap")
    assert os.access(bwrap, os.X_OK)
    run = subprocess.run([bwrap, "--ro-bind", "/", "/", "--bind", "/a b", "/a b", "--unshare-pid", "--",
                          "sh", "-c", 'printf "%s|" "$@"; exit 3', "sh", "x y", "--"], capture_output=True, text=True)
    assert (run.returncode, run.stdout) == (3, "x y|--|")
    assert subprocess.run([bwrap, "--ro-bind", "/", "/", "true"], capture_output=True).returncode == 1


def test_an_in_place_launch_goes_on_under_the_replays_path(copied, tmp_path):
    repo = tmp_path / "toy"
    repo.mkdir()
    for args in (("init", "-q", "-b", "master"), ("commit", "-q", "--allow-empty", "-m", "init"),
                 ("clone", "-q", "--bare", ".", str(tmp_path / "origin.git")),
                 ("remote", "add", "origin", str(tmp_path / "origin.git")), ("fetch", "-q", "origin"),
                 ("remote", "set-head", "origin", "master"), ("checkout", "-q", "-b", "night-work")):
        subprocess.run(["git", *args], cwd=repo, env=ENV, check=True, capture_output=True)
    path = f"{copied}/replay/bin:{ENV.get('PATH', '/usr/bin:/bin')}"
    r = subprocess.run(["bash", str(REPO / "scripts" / "create-overnight-state.sh"), "--end-time", "2h",
                        "--session-id", "s-stand-in", "--project-dir", str(repo)], cwd=repo, capture_output=True,
                       text=True, timeout=300, env={**ENV, "PATH": path})
    assert r.returncode == 0, r.stderr
    assert '"isolation_kind": "in_place"' in (repo / ".claude" / "overnight-state-s-stand-in.json").read_text()
