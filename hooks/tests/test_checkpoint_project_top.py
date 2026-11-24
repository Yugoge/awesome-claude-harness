"""A snapshot is of the project: never of a repository above it, never minutes, nothing left running.

hooks/lib/checkpoint-core.sh snapshots a project only when the project's directory is the top of
its repository's working tree (checkpoint_project_top). A project that is a folder below a larger
repository gets no snapshot: the snapshot ref is the repository's, one per branch, and recovery
(docs/reference/checkpoint-mechanism.md) restores the repository's tree, so a snapshot of that
repository would stage and commit everything above the project. A project in no repository gets
none either. The tree scans a snapshot runs (auto-commit.sh's status, the library's add -A) are
bounded by CHECKPOINT_SCAN_TIMEOUT; at the bound timeout ends git and every process it started.

Every repository here is a throwaway one under tmp_path, GIT_CEILING_DIRECTORIES keeps git from
looking above tmp_path, and the hooks run from a copy of hooks/lib in tmp_path with a throwaway
home, state directory, temp directory and git configuration.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ("auto-commit.sh", "posttool-git-checkpoint.sh")


def _git(env: dict, repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], env=env, text=True,
                          capture_output=True, check=True).stdout.strip()


def _left_running(tmp_path: Path) -> list[str]:
    """Processes whose command line or working directory lies in tmp_path."""
    found = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            cmd = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
            cwd = os.readlink(proc / "cwd")
        except OSError:
            continue
        if str(tmp_path) in cmd or cwd.startswith(str(tmp_path)):
            found.append(f"{proc.name}: {cmd.strip()} (cwd {cwd})")
    return found


@pytest.fixture
def sandbox(tmp_path: Path) -> tuple[Path, dict]:
    hooks = tmp_path / "harness" / "hooks"
    shutil.copytree(ROOT / "hooks" / "lib", hooks / "lib", ignore=shutil.ignore_patterns("__pycache__"))
    for name in SCRIPTS:
        shutil.copy2(ROOT / "hooks" / name, hooks / name)
    (tmp_path / "gitconfig").write_text("")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "HOME": str(tmp_path / "home"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "config"),
        "CHECKPOINT_LOG_DIR": str(tmp_path / "config" / "logs"),
        "CLAUDE_STATE_DIR": str(tmp_path / "state"),
        "TMPDIR": str(tmp_path / "tmp"),
        "CHECKPOINT_NO_PUSH": "1",
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    for key in ("HOME", "CLAUDE_STATE_DIR", "TMPDIR", "CHECKPOINT_LOG_DIR"):
        Path(env[key]).mkdir(parents=True)
    return tmp_path, env


def _repo(env: dict, top: Path, files: dict[str, str]) -> None:
    top.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(top)], env=env, check=True)
    for name, text in files.items():
        (top / name).parent.mkdir(parents=True, exist_ok=True)
        (top / name).write_text(text)
    _git(env, top, "add", "-A")
    _git(env, top, "commit", "-q", "-m", "init")


def _run(tmp_path: Path, env: dict, script: str, cwd: Path, *, extra: dict | None = None,
         stdin: str = "", limit: float = 60) -> tuple[int | None, float, str]:
    """Run a hook from the copied home as Claude Code runs it in cwd; None when killed at limit."""
    start = time.monotonic()
    try:
        proc = subprocess.run(["bash", str(tmp_path / "harness" / "hooks" / script)], input=stdin,
                              text=True, capture_output=True, cwd=str(cwd), timeout=limit,
                              env={**env, "CLAUDE_PROJECT_DIR": str(cwd), **(extra or {})})
        return proc.returncode, time.monotonic() - start, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:  # the Stop coordinator's phase limit: bash killed, children not
        return None, time.monotonic() - start, ""


def _scans(trace: Path) -> list[tuple[str, str]]:
    """(command, working tree) of every tree scan (git status, git add) in a GIT_TRACE2_EVENT file: the work a
    snapshot does, counted instead of timed."""
    names, trees = {}, {}
    for line in (trace.read_text().splitlines() if trace.exists() else []):
        event = json.loads(line)
        if event.get("event") == "cmd_name":
            names[event["sid"]] = event["name"]
        elif event.get("event") == "def_repo":
            trees[event["sid"]] = event.get("worktree", "")
    return sorted((name, trees.get(sid, "")) for sid, name in names.items() if name in ("status", "add"))


def _library(tmp_path: Path, env: dict, cwd: Path, work_dir: str) -> tuple[int, str]:
    lib = tmp_path / "harness" / "hooks" / "lib" / "checkpoint-core.sh"
    proc = subprocess.run(["bash", "-c", '. "$1"; write_checkpoint "$2" test; echo "rc=$? ref=$checkpoint_ref"',
                           "t", str(lib), work_dir], text=True, capture_output=True, cwd=str(cwd), env=env,
                          timeout=60)
    return proc.returncode, proc.stdout.strip()


def _log(env: dict) -> str:
    log = Path(env["CHECKPOINT_LOG_DIR"]) / "checkpoint.log"
    return log.read_text() if log.exists() else ""


def _state(env: dict, top: Path) -> tuple:
    """What a snapshot of top would change: its refs, its index bytes, its object store."""
    objects = sorted(str(p.relative_to(top)) for p in (top / ".git" / "objects").rglob("*") if p.is_file())
    return (_git(env, top, "for-each-ref"), (top / ".git" / "index").read_bytes(), objects)


def test_a_project_below_a_larger_repository_never_snapshots_that_repository(sandbox) -> None:
    tmp_path, env = sandbox
    outer = tmp_path / "outer"
    _repo(env, outer, {"a.txt": "a\n"})
    (outer / "a.txt").write_text("a changed above the project\n")
    (outer / "stray.txt").write_text("untracked above the project\n")
    for i in range(2000):  # a tree above the project that is costly to scan
        (outer / "bulk" / f"d{i % 20}").mkdir(parents=True, exist_ok=True)
        (outer / "bulk" / f"d{i % 20}" / f"f{i}.txt").write_text(f"{i}\n")
    project = outer / "proj"
    (project / "src").mkdir(parents=True)
    (project / "src" / "p.txt").write_text("the project's own file\n")
    before = _state(env, outer)

    trace = tmp_path / "trace2.json"
    rc, took, out = _run(tmp_path, env, "auto-commit.sh", project, extra={"GIT_TRACE2_EVENT": str(trace)})
    assert rc == 0, out
    rc2, took2, out2 = _run(tmp_path, env, "posttool-git-checkpoint.sh", project,
                            extra={"GIT_CHECKPOINT_THRESHOLD": "1", "GIT_TRACE2_EVENT": str(trace)},
                            stdin=json.dumps({"tool_input": {"file_path": str(project / "src" / "p.txt")}}))
    assert rc2 == 0, out2
    print(f"below a larger repository: auto-commit.sh {took:.2f}s, posttool {took2:.2f}s")
    assert _state(env, outer) == before, "the repository above the project was staged or committed"
    for work_dir, cwd in (("", project), (str(project), tmp_path), (str(project / "src"), tmp_path)):
        assert _library(tmp_path, env, cwd, work_dir)[1] == "rc=2 ref=", work_dir
    assert "not the top of its repository" in _log(env)
    assert _scans(trace) == [], "the tree above the project was scanned"
    assert _left_running(tmp_path) == []
    # the repository's own top is still snapshotted, with everything in it
    assert _library(tmp_path, env, outer, "")[1] == "rc=0 ref=refs/checkpoints/main"
    assert "proj/src/p.txt" in _git(env, outer, "ls-tree", "-r", "--name-only", "refs/checkpoints/main")


def test_a_project_in_no_repository_gets_no_snapshot_and_no_repository(sandbox) -> None:
    tmp_path, env = sandbox
    project = tmp_path / "lone"
    project.mkdir()
    (project / "p.txt").write_text("no repository here\n")

    trace = tmp_path / "trace2.json"
    rc, took, out = _run(tmp_path, env, "auto-commit.sh", project, extra={"GIT_TRACE2_EVENT": str(trace)})
    assert rc == 0 and "Not a git repository" in out, out
    assert _library(tmp_path, env, project, "")[1] == "rc=2 ref="
    assert not (project / ".git").exists()
    assert _scans(trace) == [] and _left_running(tmp_path) == []


def test_an_ordinary_project_is_snapshotted_and_its_index_left_alone(sandbox) -> None:
    tmp_path, env = sandbox
    project = tmp_path / "plain"
    _repo(env, project, {"a.txt": "a\n", "sub/b.txt": "b\n"})
    (project / "a.txt").write_text("a changed\n")
    (project / "new.txt").write_text("new\n")
    index = (project / ".git" / "index").read_bytes()

    trace = tmp_path / "trace2.json"
    rc, took, out = _run(tmp_path, env, "auto-commit.sh", project, extra={"GIT_TRACE2_EVENT": str(trace)})
    assert rc == 0 and "Checkpoint saved" in out, out
    tree = _git(env, project, "ls-tree", "-r", "--name-only", "refs/checkpoints/main").splitlines()
    assert tree == ["a.txt", "new.txt", "sub/b.txt"]
    assert _git(env, project, "show", "refs/checkpoints/main:a.txt") == "a changed"
    assert (project / ".git" / "index").read_bytes() == index
    assert _git(env, project, "rev-list", "--count", "main") == "1"
    # one status and one add -A of the project: the work counted, not timed
    assert _scans(trace) == [("add", str(project)), ("status", str(project))], _scans(trace)
    assert _left_running(tmp_path) == []
    # from a folder inside it the project is that folder, not this repository: no snapshot
    assert _library(tmp_path, env, project / "sub", "")[1] == "rc=2 ref="


def test_a_scan_past_its_bound_is_ended_with_every_process_it_started(sandbox) -> None:
    tmp_path, env = sandbox
    project = tmp_path / "slow"
    _repo(env, project, {".gitattributes": "*.dat filter=slow\n"})
    filt = tmp_path / "slow-filter.sh"  # a clean filter that takes 120 s per file: far past every bound here
    filt.write_text("#!/bin/sh\nsleep 120\ncat\n")
    filt.chmod(0o755)
    _git(env, project, "config", "filter.slow.clean", str(filt))
    _git(env, project, "config", "filter.slow.required", "true")
    (project / "big.dat").write_text("data\n")

    # 60 s: the hook is killed there as the Stop coordinator kills a phase past its limit (rc None). An rc of 1
    # means the 2 s scan bound ended the scan, not the limit and not the filter's 120 s: no clock is compared.
    rc, took, out = _run(tmp_path, env, "auto-commit.sh", project,
                         extra={"CHECKPOINT_SCAN_TIMEOUT": "2"}, limit=60)
    print(f"slow scan: rc={rc} {took:.2f}s")
    assert _left_running(tmp_path) == [], "the snapshot's git outlived its hook"
    assert rc == 1 and "Checkpoint failed" in out, (rc, out)
    assert "ran past 2s" in _log(env)
    assert _git(env, project, "for-each-ref", "refs/checkpoints") == ""
