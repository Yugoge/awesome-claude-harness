"""The filesystem root is never the top of a project: a snapshot with it as the only repository writes nothing.

Once a repository lay at the filesystem root by accident, and the snapshot of a session in no repository of its own
found it and committed the machine into it. hooks/lib/checkpoint-core.sh (checkpoint_project_top) now refuses a
repository whose top is "/", for a session below it or at it, and says so once in checkpoints' log.

The root is simulated: a private user and mount namespace of this test process alone chroots into a made-up
directory that holds the repository, so the code under test sees that directory as "/". The real root is not touched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BOUND = ("usr", "etc", "dev", "proc")  # the programs and their libraries, read only, and ignored by the made-up root's repository
LINKED = ("bin", "sbin", "lib", "lib64")
BOUND_EXTRA: list[str] = []  # LINKED names that are directories here


def _namespace_available() -> bool:
    try:
        return subprocess.run(["unshare", "-rm", "true"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not _namespace_available(), reason="no private user and mount namespace here")


def _git(env: dict, repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], env=env, text=True, capture_output=True,
                          check=True).stdout.strip()


@pytest.fixture
def fake_root(tmp_path: Path) -> tuple[Path, dict]:
    fr = tmp_path / "fr"
    for sub in ("h/hooks", "state", "logs", "home", "tmp", "sub", "own"):
        (fr / sub).mkdir(parents=True)
    for name in BOUND:
        (fr / name).mkdir()
    for name in LINKED:  # the host's own layout: a link into usr, or a directory
        host = Path("/") / name
        if host.is_symlink():
            (fr / name).symlink_to(os.readlink(host))
        elif host.is_dir():
            BOUND_EXTRA.append(name)
            (fr / name).mkdir()
    shutil.copytree(ROOT / "hooks" / "lib", fr / "h" / "hooks" / "lib", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "hooks" / "doc_sync", fr / "h" / "hooks" / "doc_sync",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("auto-commit.sh", "session-gitignore-propagate.sh", "prompt-workflow.py"):
        shutil.copy2(ROOT / "hooks" / name, fr / "h" / "hooks" / name)
    (tmp_path / "gitconfig").write_text("[safe]\n\tdirectory = *\n")
    (fr / "gitconfig").write_text("[safe]\n\tdirectory = *\n")
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
           "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    subprocess.run(["git", "init", "-q", "-b", "main", str(fr)], env=env, check=True)
    (fr / ".gitignore").write_text("".join(f"/{n}\n" for n in BOUND + LINKED))
    (fr / "stray.txt").write_text("a file of the machine\n")
    _git(env, fr, "add", "-A")
    _git(env, fr, "commit", "-q", "-m", "root repository")
    (fr / "stray.txt").write_text("changed\n")  # something to snapshot
    (fr / "sub" / "p.txt").write_text("the session's own file\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(fr / "own")], env=env, check=True)
    (fr / "own" / "o.txt").write_text("o\n")
    _git(env, fr / "own", "add", "-A")
    _git(env, fr / "own", "commit", "-q", "-m", "own")
    (fr / "own" / "o.txt").write_text("o changed\n")
    return fr, env



def _in_root(fr: Path, cwd: str, *argv: str) -> subprocess.CompletedProcess:
    """argv run with the made-up root as "/" and cwd as its directory, as a hook runs in a session there."""
    binds = " ".join(f'mount --rbind /{n} "$FR/{n}"; mount -o remount,bind,ro "$FR/{n}" 2>/dev/null;'
                     for n in BOUND + tuple(BOUND_EXTRA))
    script = (f'set -e; FR="$1"; shift; mount --make-rprivate /; {binds} '
              'exec /usr/sbin/chroot "$FR" /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME=/home '
              'CLAUDE_STATE_DIR=/state CLAUDE_CONFIG_DIR=/home/.claude CHECKPOINT_LOG_DIR=/logs TMPDIR=/tmp '
              f'CHECKPOINT_NO_PUSH=1 GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/gitconfig CLAUDE_PROJECT_DIR={cwd} '
              'GIT_AUTHOR_NAME=T GIT_AUTHOR_EMAIL=t@example.invalid GIT_COMMITTER_NAME=T '
              'GIT_COMMITTER_EMAIL=t@example.invalid /usr/bin/bash -c \'cd "$0" && exec "$@"\' ' + cwd + ' "$@"')
    return subprocess.run(["unshare", "-rm", "bash", "-c", script, "_", str(fr), *argv], text=True,
                          capture_output=True, timeout=90)


def _stop_hook(fr: Path, cwd: str) -> subprocess.CompletedProcess:
    return _in_root(fr, cwd, "bash", "/h/hooks/auto-commit.sh")


def _py(fr: Path, cwd: str, code: str) -> str:
    proc = _in_root(fr, cwd, "python3", "-I", "-c", "import sys; sys.path[:0] = ['/h/hooks', '/h/hooks/lib']\n" + code)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout.strip()


def _refs(env: dict, repo: Path) -> str:
    return _git(env, repo, "for-each-ref", "refs/checkpoints")


def _log(fr: Path) -> list[str]:
    log = fr / "logs" / "checkpoint.log"
    return log.read_text().splitlines() if log.exists() else []


@pytest.mark.parametrize("cwd", ["/sub", "/"])
def test_the_root_repository_is_never_snapshotted_and_the_log_says_so_once(fake_root, cwd) -> None:
    fr, env = fake_root
    proc = _stop_hook(fr, cwd)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _refs(env, fr) == "", "a snapshot of the whole machine was written into the repository at the root"
    reasons = [line for line in _log(fr) if "filesystem root" in line]
    assert len(reasons) == 1 and len(_log(fr)) == 1, _log(fr)


def test_a_session_inside_its_own_repository_is_snapshotted_as_before(fake_root) -> None:
    fr, env = fake_root
    proc = _stop_hook(fr, "/own")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "checkpoints/main" in _refs(env, fr / "own")
    assert _refs(env, fr) == ""
    assert not any("filesystem root" in line for line in _log(fr))


def test_no_other_resolver_takes_the_root_repository_for_a_project(fake_root) -> None:
    """Each place that asks for a repository's top, in a session below the root repository: no answer, nothing written."""
    fr, env = fake_root
    exclude = fr / ".git" / "info" / "exclude"
    before = exclude.read_text() if exclude.exists() else ""
    proc = _in_root(fr, "/sub", "bash", "/h/hooks/session-gitignore-propagate.sh")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (exclude.read_text() if exclude.exists() else "") == before, "the root repository's exclude file was written"
    assert _py(fr, "/sub", "from pathlib import Path\nfrom doc_sync.config import work_tree_root\n"
                           "print(work_tree_root(Path('/sub')))") == "None"
    assert _py(fr, "/sub", "from pathlib import Path\nfrom doc_sync.folder_doc import _repo_root\n"
                           "print(_repo_root(Path('/sub')))") == "None"
    assert _py(fr, "/sub", "import fact_cache\nprint(fact_cache.repository('/sub'))") == "None"
    assert _py(fr, "/sub", "import importlib.util as u\n"
                           "s = u.spec_from_file_location('pw', '/h/hooks/prompt-workflow.py'); m = u.module_from_spec(s)\n"
                           "s.loader.exec_module(m)\nprint(m._try_git_toplevel())") == "None"
    assert _py(fr, "/own", "from pathlib import Path\nfrom doc_sync.config import work_tree_root\n"
                           "print(work_tree_root(Path('/own')))") == "/own"
