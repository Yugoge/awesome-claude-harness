"""The filesystem root is never the top of a project: a snapshot with it as the only repository writes nothing.

Once a repository lay at the filesystem root by accident, and the snapshot of a session in no repository of its own
found it and committed the machine into it. hooks/lib/checkpoint-core.sh (checkpoint_project_top) now refuses a
repository whose top is "/", for a session below it or at it, and says so once in checkpoints' log.

The root is simulated: a private mount namespace (hooks/tests/_private_ns.py: root, a user namespace or sudo) chroots into a made-up
directory that holds the repository, so the code under test sees that directory as "/". The real root is not touched.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _private_ns  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BOUND = ("usr", "etc", "dev", "proc")  # the programs and their libraries, read only, and ignored by the made-up root's repository
LINKED = ("bin", "sbin", "lib", "lib64")
BOUND_EXTRA: list[str] = []  # LINKED names that are directories here
SHIM = ".pyroot"  # the made-up root's folder whose python3 is the test run's interpreter, first on its search path
OWN = ("h", "state", "logs", "home", "tmp", "sub", "own", "docs", "gitconfig", "stray.txt", SHIM)  # names the fixture uses


def _installation() -> tuple[Path | None, Path]:
    """The folder of the test run's interpreter installation to show inside the made-up root at the same path (None
    where the system folders it binds hold it), and the interpreter's real program. A virtual environment is its base."""
    base, exe = Path(os.path.realpath(sys.base_prefix)), Path(os.path.realpath(sys._base_executable))
    top = base.parts[1] if len(base.parts) > 1 else ""
    if top in BOUND + LINKED:
        return None, exe
    # below the made-up root's own HOME or temp folder the installation is shown at its path inside them (the folders stay)
    assert top and (top not in OWN or top in ("home", "tmp") and len(base.parts) > 2) and exe.is_relative_to(base), (
        f"the test run's interpreter ({exe}, installation {base}) lies at or below a name the made-up root uses itself "
        "(other than below home or tmp) or outside its installation folder; run the tests with an interpreter installed elsewhere")
    return base, exe


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
    inst, exe = _installation()
    (fr / SHIM).mkdir()
    (fr / SHIM / "python3").symlink_to(exe)  # the name python3, for a direct call and for one by name from a script
    if inst:
        (fr / str(inst).lstrip("/")).mkdir(parents=True)  # where the installation is shown; not content of the repository
    # the ignore list names exactly what was added: the bound folders, the python3 folder, the installation's own place
    (fr / ".gitignore").write_text("".join(f"/{n}\n" for n in BOUND + LINKED + (SHIM,))
                                   + (re.sub(r"([*?\[\\ #!])", r"\\\1", str(inst)) + "\n" if inst else ""))
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
    """argv run with the made-up root as "/" and cwd as its directory, as a hook runs in a session there. The root is
    entered by the test interpreter's own chroot call (no chroot or env program); python3 inside is that interpreter."""
    inst, exe = _installation()
    shown = [f"/{n}" for n in BOUND + tuple(BOUND_EXTRA)] + ([str(inst)] if inst else [])
    binds = " ".join(f'mount --rbind {shlex.quote(d)} "$FR"{shlex.quote(d)}; '
                     f'mount -o remount,bind,ro "$FR"{shlex.quote(d)} 2>/dev/null;' for d in shown)
    # a build with a shared interpreter library: the loader is told where it lies, outside and inside the root
    lib = sysconfig.get_config_var("LIBDIR") if sysconfig.get_config_var("Py_ENABLE_SHARED") and inst else ""
    ld = {"LD_LIBRARY_PATH": lib} if lib and Path(lib).is_relative_to(inst) else {}
    script = (f'set -e; FR="$1"; shift; mount --make-rprivate /; {binds} '
              f'{"export LD_LIBRARY_PATH=" + shlex.quote(lib) + ";" if ld else ""} exec "$@"')
    env = {"PATH": f"/{SHIM}:/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/home", "CLAUDE_STATE_DIR": "/state",
           "CLAUDE_CONFIG_DIR": "/home/.claude", "CHECKPOINT_LOG_DIR": "/logs", "TMPDIR": "/tmp", "CHECKPOINT_NO_PUSH": "1",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/gitconfig", "CLAUDE_PROJECT_DIR": cwd,
           "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "T",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", **ld}
    way = _private_ns.require("the made-up root's cases")  # one route for the folder: root, user namespace or sudo
    enter = ("import json, os, sys\nfr, cwd, env = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])\n"
             "os.chroot(fr); os.chdir('/')\n"
             "os.execvpe('bash', ['bash', '-c', 'cd \"$0\" && exec \"$@\"', cwd, *sys.argv[4:]], env)")
    return subprocess.run(_private_ns.unshare_plain(way, ["bash", "-c", script, "_", str(fr), str(exe), "-I", "-c", enter,
                                                          str(fr), cwd, json.dumps(env), *argv]),
                          env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")}, text=True, capture_output=True, timeout=90)


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


def test_python3_inside_the_made_up_root_is_the_interpreter_of_the_test_run(fake_root) -> None:
    """The name python3, by a direct call and from a shell line, reaches the test run's installation, not the machine's."""
    fr, _ = fake_root
    code = "import os, sys; print(sys.hexversion, os.path.realpath(sys.base_prefix), os.path.realpath(sys._base_executable))"
    want = f"{sys.hexversion} {os.path.realpath(sys.base_prefix)} {os.path.realpath(sys._base_executable)}"
    direct = _in_root(fr, "/", "python3", "-I", "-c", code)
    shell = _in_root(fr, "/", "bash", "-c", f"python3 -I -c '{code}'")
    assert (direct.stdout.strip(), shell.stdout.strip()) == (want, want), direct.stderr + shell.stderr
    inst, _ = _installation()  # what was added for it is no content of the root's repository, listed as nothing
    status = _in_root(fr, "/", "git", "-C", "/", "status", "--porcelain")
    assert status.returncode == 0, status.stderr
    added = [SHIM] + ([str(inst).lstrip("/")] if inst else [])
    seen = [ln[3:].strip('"').rstrip("/") for ln in status.stdout.splitlines()]
    assert not [p for p in seen for a in added if p == a or a.startswith(p + "/") or p.startswith(a + "/")], status.stdout
