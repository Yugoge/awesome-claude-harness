"""A nested repository with no commit, and the harness's scratch root of a project, never make
a checkpoint snapshot fail as a whole.

Live, a test fixture made a repository with no commit below an agent's scratch directory, which
lies in the project under .claude/scratch and was not ignored there: every `git add -A` of the
snapshot failed ("does not have a commit checked out"), and every command after it ran with no
snapshot. Here, in throwaway projects: such a repository outside the scratch root is left out and
named (log and notice), the rest is written; the scratch root, whatever it holds, is never part of
a snapshot and leaving it out still counts as complete; git does not see the scratch root at all,
one that existed before included; a dispatch declaring output there is not refused as ignored.
A nested repository that has commits stays what it was: one gitlink entry, never its files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REF = "refs/checkpoints/main"
SCRATCH = Path(".claude", "scratch")


def _git(env: dict, repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], env=env, text=True,
                          capture_output=True, check=True).stdout.strip()


@pytest.fixture
def world(tmp_path: Path) -> tuple[Path, dict]:
    home = tmp_path / "harness"
    shutil.copytree(ROOT / "hooks" / "lib", home / "hooks" / "lib",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "gitconfig").write_text("")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8",
           "HOME": str(tmp_path / "user-home"), "CLAUDE_CONFIG_DIR": str(tmp_path / "config"),
           "CLAUDE_STATE_DIR": str(tmp_path / "state"), "TMPDIR": str(tmp_path / "tmp"),
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
           "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    for key in ("HOME", "CLAUDE_STATE_DIR", "TMPDIR"):
        Path(env[key]).mkdir(parents=True)
    (tmp_path / "config" / "logs").mkdir(parents=True)
    return home, env


def _project(env: dict, path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], env=env, check=True)
    (path / "README.md").write_text("hello\n")
    _git(env, path, "add", "-A")
    _git(env, path, "commit", "-q", "-m", "init")
    return path


def _empty_repo(env: dict, path: Path) -> None:
    """A repository with no commit and a file in its work tree."""
    subprocess.run(["git", "init", "-q", str(path)], env=env, check=True)
    (path / "f.txt").write_text("inner\n")


def _old_scratch_root(env: dict, repo: Path) -> Path:
    """A scratch root as a session of an older version left it: agents' scratch directories, a
    test's repository with no commit, one with commits, thousands of files, no ignore file."""
    agent = repo / SCRATCH / "s1" / "dev" / "a1"
    _empty_repo(env, agent / "pytest-of-x" / "pytest-3" / "w0" / "proj")
    full = agent / "full"
    _empty_repo(env, full)
    _git(env, full, "add", "-A")
    _git(env, full, "commit", "-q", "-m", "x")
    bulk = agent / "bulk"
    bulk.mkdir()
    for i in range(3000):
        (bulk / f"f{i}.txt").write_text("x\n")
    return repo / SCRATCH


def _snapshot(home: Path, env: dict, repo: Path) -> tuple[int, str, str]:
    """One write_checkpoint run: (rc, checkpoint_left_out, checkpoint_notice)."""
    proc = subprocess.run(
        ["bash", "-c", '. "$0"; write_checkpoint "$1" test >/dev/null 2>&1; rc=$?;'
         ' printf "%s\\n%s\\n%s" "$rc" "$checkpoint_left_out" "$checkpoint_notice"',
         str(home / "hooks" / "lib" / "checkpoint-core.sh"), str(repo)],
        env=env, text=True, capture_output=True, timeout=120)
    rc, left_out, notice = proc.stdout.split("\n", 2)
    return int(rc), left_out, notice


def _log(env: dict) -> str:
    log = Path(env["CLAUDE_CONFIG_DIR"]) / "logs" / "checkpoint.log"
    return log.read_text() if log.exists() else ""


def _count(repo: Path) -> str:
    return (repo / ".git" / "checkpoint-fail-count.main").read_text().split()[0]


def test_nested_repo_with_no_commit_is_left_out_and_named(world, tmp_path: Path) -> None:
    home, env = world
    repo = _project(env, tmp_path / "project")
    _empty_repo(env, repo / "vendor" / "inner")
    (repo / "notes.txt").write_text("ordinary note\n")
    for n in (1, 2):
        rc, left_out, notice = _snapshot(home, env, repo)
        assert rc == 0, _log(env)
        assert left_out == "1 nested repositor(ies) with no commit: vendor/inner"
        assert notice.startswith(f"Checkpoint snapshot left out {left_out}, see logs/checkpoint.log; "
                                 f"no complete snapshot of {REF} since "), notice
        assert notice.endswith(f"({n} in a row)"), notice
        assert _log(env).count(f"[WARN] left out {left_out} (ref={REF})") == n
        assert _count(repo) == str(n)  # leaving a path out is no complete snapshot
    tree = _git(env, repo, "ls-tree", "-r", "--name-only", REF).splitlines()
    assert tree == ["README.md", "notes.txt"]


def test_scratch_root_never_enters_a_snapshot_and_counts_as_complete(world, tmp_path: Path) -> None:
    home, env = world
    repo = _project(env, tmp_path / "project")
    _old_scratch_root(env, repo)
    (repo / "notes.txt").write_text("ordinary note\n")
    rc, left_out, notice = _snapshot(home, env, repo)
    assert (rc, left_out, notice) == (0, "", ""), _log(env)
    assert "add -A failed" not in _log(env)
    assert _git(env, repo, "ls-tree", "-r", "--name-only", REF).splitlines() == ["README.md", "notes.txt"]
    assert not (repo / ".git" / "checkpoint-fail-count.main").exists() or _count(repo) == "0"


def test_both_at_once_only_the_outside_one_is_named(world, tmp_path: Path) -> None:
    """The live shape and the acceptance reproduction: one in the scratch root, one elsewhere."""
    home, env = world
    repo = _project(env, tmp_path / "project")
    _old_scratch_root(env, repo)
    _empty_repo(env, repo / "sub" / "inner")
    (repo / "b.txt").write_text("b\n")
    rc, left_out, _ = _snapshot(home, env, repo)
    assert (rc, left_out) == (0, "1 nested repositor(ies) with no commit: sub/inner"), _log(env)
    assert _git(env, repo, "ls-tree", "-r", "--name-only", REF).splitlines() == ["README.md", "b.txt"]


def _untracked(env: dict, repo: Path) -> list[str]:
    return _git(env, repo, "status", "--porcelain", "--untracked-files=all").splitlines()


def test_git_does_not_see_a_scratch_root_that_existed_before(world, tmp_path: Path) -> None:
    home, env = world
    repo = _project(env, tmp_path / "project")
    _old_scratch_root(env, repo)
    assert any(line.startswith("?? .claude/scratch/") for line in _untracked(env, repo))
    exclude = (repo / ".git" / "info" / "exclude").read_bytes()
    _snapshot(home, env, repo)
    assert _untracked(env, repo) == []
    assert _git(env, repo, "check-ignore", ".claude/scratch/s1/dev/a1/x.txt") == ".claude/scratch/s1/dev/a1/x.txt"
    assert (repo / ".git" / "info" / "exclude").read_bytes() == exclude  # the project's .git is not edited


def test_the_snapshot_is_the_one_writer_of_the_ignore_file(world, tmp_path: Path) -> None:
    """A session that started before, with no new session start: the scratch root an agent makes
    while it runs is hidden by the next snapshot. The SessionStart hook writes nothing there, and
    no other file of hooks/ or scripts/ names the ignore file (one writer per artifact)."""
    home, env = world
    repo = _project(env, tmp_path / "project")
    subprocess.run(["bash", str(ROOT / "hooks" / "session-gitignore-propagate.sh")], input="{}", text=True,
                   cwd=repo, env=dict(env, CLAUDE_PROJECT_DIR=str(repo)), check=True, timeout=30)
    assert not (repo / SCRATCH).exists()
    (repo / SCRATCH / "s1" / "dev" / "a1").mkdir(parents=True)
    (repo / SCRATCH / "s1" / "dev" / "a1" / "out.txt").write_text("x\n")
    assert _untracked(env, repo) == ["?? .claude/scratch/s1/dev/a1/out.txt"]
    _snapshot(home, env, repo)
    assert _untracked(env, repo) == []
    assert (repo / SCRATCH / ".gitignore").read_text() == "*\n"
    writers = sorted(str(p.relative_to(ROOT)) for d in ("hooks", "scripts") for p in (ROOT / d).rglob("*")
                     if p.is_file() and p.suffix in (".sh", ".py", "") and "tests" not in p.parts
                     and re.search(r"scratch\S*/\.gitignore", p.read_text(errors="replace")))
    assert writers == ["hooks/lib/checkpoint-core.sh"]


def test_nested_repo_with_commits_stays_one_gitlink(world, tmp_path: Path) -> None:
    home, env = world
    repo = _project(env, tmp_path / "project")
    full = repo / "vendor" / "full"
    _empty_repo(env, full)
    _git(env, full, "add", "-A")
    _git(env, full, "commit", "-q", "-m", "x")
    rc, left_out, _ = _snapshot(home, env, repo)
    assert (rc, left_out) == (0, ""), _log(env)
    entry = _git(env, repo, "ls-tree", "-r", REF, "vendor/full")
    assert entry.startswith("160000 commit " + _git(env, full, "rev-parse", "HEAD")), entry


def test_dispatch_declaring_output_in_the_scratch_root_is_not_refused(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / "docs" / "dev").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / SCRATCH).mkdir(parents=True)
    (root / SCRATCH / ".gitignore").write_text("*\n")
    (root / ".gitignore").write_text("/build/\n")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), HOME=str(tmp_path / "home"),
               CLAUDE_CONFIG_DIR=str(tmp_path / "home" / ".claude"))
    env.pop("CLAUDE_HOME", None)

    def gate(task: str, created: list[str]) -> int:
        (root / "docs" / "dev" / f"dev-report-{task}.json").write_text(
            json.dumps({"dev": {"files_modified": [], "files_created": created}}))
        payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "qa", "description": "d",
                   "prompt": f"Dev report file: docs/dev/dev-report-{task}.json\n"}}
        return subprocess.run([sys.executable, str(ROOT / "hooks" / "pretool-gitignore-preflight.py")],
                              input=json.dumps(payload), capture_output=True, text=True, env=env,
                              cwd=str(root), timeout=60).returncode

    assert gate("20261120-090001", ["build/app.js"]) == 2  # the check is reached: an ignored product
    assert gate("20261120-090000", [".claude/scratch/s1/dev/a1/out.json",
                                    str(root / SCRATCH / "s1" / "dev" / "a1" / "o.txt")]) == 0


# The states a project's scratch root can be in, and how each is made. "c-*" is a root ignored by a
# rule outside it: git then names the root (or its ignored parent) when a pathspec names it.
STATES = ("a-none", "b-unignored", "c-top", "c-top-parent", "c-exclude", "c-global", "d-own", "e-user")


def _state(env: dict, repo: Path, state: str) -> None:
    if state != "a-none":
        (repo / SCRATCH / "s1" / "dev" / "a1").mkdir(parents=True)
        (repo / SCRATCH / "s1" / "dev" / "a1" / "out.txt").write_text("x\n")
    rule = {"c-top": repo / ".gitignore", "c-top-parent": repo / ".gitignore",
            "c-exclude": repo / ".git" / "info" / "exclude",
            "c-global": Path(env["HOME"]) / ".config" / "git" / "ignore",
            "d-own": repo / SCRATCH / ".gitignore", "e-user": repo / SCRATCH / ".gitignore"}.get(state)
    if rule:
        rule.parent.mkdir(parents=True, exist_ok=True)
        with rule.open("a") as fh:
            fh.write({"c-top-parent": ".claude/\n", "d-own": "*\n", "e-user": "*.log\n"}.get(state, ".claude/scratch/\n"))
    if state in ("c-top", "c-top-parent"):
        _git(env, repo, "add", ".gitignore")
        _git(env, repo, "commit", "-q", "-m", "ignore")


def _files(repo: Path) -> set[str]:
    return {str(p.relative_to(repo)) for p in repo.rglob("*") if ".git" not in p.relative_to(repo).parts[:1]}


@pytest.mark.parametrize("nested", ("none", "in-scratch", "elsewhere", "both"))
@pytest.mark.parametrize("state", STATES)
def test_every_scratch_root_state_is_snapshotted_without_it(world, tmp_path: Path, state: str, nested: str) -> None:
    """Each state, with and without a repository with no commit inside the scratch root and one
    elsewhere: the snapshot is written without the scratch root, the outside one is named; the
    project gains no file but the self-ignoring ignore file of a root nothing ignored (b), and git
    reports no file it did not report before."""
    home, env = world
    repo = _project(env, tmp_path / "project")
    _state(env, repo, state)
    if nested in ("in-scratch", "both") and state != "a-none":
        _empty_repo(env, repo / SCRATCH / "s1" / "dev" / "a1" / "pytest-3" / "proj")
    if nested in ("elsewhere", "both"):
        _empty_repo(env, repo / "sub" / "inner")
    (repo / "b.txt").write_text("b\n")
    files, status = _files(repo), set(_untracked(env, repo))
    for _ in (1, 2):  # the second snapshot meets the state the first one left (d after b)
        rc, left_out, _notice = _snapshot(home, env, repo)
        assert rc == 0, _log(env)
        assert left_out == ("1 nested repositor(ies) with no commit: sub/inner" if nested in ("elsewhere", "both") else "")
        tree = _git(env, repo, "ls-tree", "-r", "--name-only", REF).splitlines()
        assert tree == sorted({"README.md", "b.txt"} | ({".gitignore"} if state in ("c-top", "c-top-parent") else set()))
        gained = _files(repo) - files
        assert gained == ({".claude/scratch/.gitignore"} if state == "b-unignored" else set()), gained
        assert set(_untracked(env, repo)) <= status
    if state == "b-unignored":
        assert not any(".claude/scratch" in line for line in _untracked(env, repo))


def test_the_harness_home_with_its_own_ignore_file_is_snapshotted(world, tmp_path: Path) -> None:
    """The harness's own layout: the project is the harness home (the snapshot code's own tree), its
    top-level ignore file (this tree's, as it is) ignores the scratch root."""
    _, env = world
    repo = _project(env, tmp_path / "home")
    shutil.copy(ROOT / ".gitignore", repo / ".gitignore")
    _git(env, repo, "add", ".gitignore")
    _git(env, repo, "commit", "-q", "-m", "ignore")
    shutil.copytree(ROOT / "hooks" / "lib", repo / "hooks" / "lib", ignore=shutil.ignore_patterns("__pycache__"))
    _old_scratch_root(env, repo)
    assert _git(env, repo, "check-ignore", ".claude/scratch") == ".claude/scratch"
    files = _files(repo)
    for _ in (1, 2):
        rc, left_out, _notice = _snapshot(repo, env, repo)
        assert (rc, left_out) == (0, ""), _log(env)
        tree = _git(env, repo, "ls-tree", "-r", "--name-only", REF).splitlines()
        assert ".gitignore" in tree and "hooks/lib/checkpoint-core.sh" in tree
        assert not [p for p in tree if p.startswith(".claude/")]
        assert _files(repo) == files
