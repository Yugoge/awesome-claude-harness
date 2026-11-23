"""hooks/session-git-init.sh (opt-in CLAUDE_SESSION_GIT_INIT) initialises the session's project, never a home
or a directory above it (location-rules U32).

The project is CLAUDE_PROJECT_DIR, else the hook's cwd. A directory that is the user's home, by any spelling,
or an ancestor of it (locations.is_broad_root) is no project: the hook leaves it untouched wherever it lies.
Each case runs the real hook with a throwaway HOME, global git config and no gh on PATH.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "session-git-init.sh"


def _run(base: Path, home: Path, cwd: Path, project=None) -> subprocess.CompletedProcess:
    (base / "gitconfig").write_text("[user]\n\tname = t\n\temail = t@example.invalid\n")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "CLAUDE_SESSION_GIT_INIT": "1",
           "GIT_CONFIG_GLOBAL": str(base / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CEILING_DIRECTORIES": str(base), "LANG": "C.UTF-8"}
    if project:
        env["CLAUDE_PROJECT_DIR"] = str(project)
    return subprocess.run(["bash", str(HOOK)], env=env, cwd=cwd, capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("place", ["a/home", "srv/deep/hh"])
def test_a_home_is_never_initialised_wherever_it_lies(tmp_path, place):
    home = tmp_path / place
    home.mkdir(parents=True)
    (home / "secret.txt").write_text("x\n")
    link = tmp_path / "home-link"
    link.symlink_to(home)
    for cwd in (home, link):  # the home by its own path and by a linked spelling
        proc = _run(tmp_path, home, cwd)
        assert proc.returncode == 0, proc.stderr
        assert not (home / ".git").exists(), proc.stdout + proc.stderr
    assert not (home / ".gitignore").exists()


@pytest.mark.parametrize("place", ["a/proj", "srv/deep/proj"])
def test_the_sessions_project_is_initialised_wherever_it_lies(tmp_path, place):
    home = tmp_path / "hh"
    home.mkdir()
    project = tmp_path / place
    project.mkdir(parents=True)
    (project / "a.txt").write_text("x\n")
    for cwd, named in ((project, None), (home, project)):  # the cwd, or CLAUDE_PROJECT_DIR from a home cwd
        proc = _run(tmp_path, home, cwd, named)
        assert proc.returncode == 0, proc.stderr
        assert (project / ".git").is_dir() and not (home / ".git").exists(), proc.stdout + proc.stderr
        shutil.rmtree(project / ".git")
        (project / ".gitignore").unlink(missing_ok=True)
