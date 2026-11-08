"""R14 (P1c, X7 option (B)): the shared-index sync after a private-index commit, with index.lock held.

Each update-index call of scripts/lib/session_index.py's sync (the --cacheinfo one for a modified path,
the --force-remove one for a deleted path) waits while a process holds the shared index.lock, printing
the holder; a lock no process holds and older than the sync is removed once, said on stdout; without
/proc nothing is removed; a path is reported synced only once update-index wrote it. In a linked
worktree the sync writes that worktree's own index and never meets the main index.lock.

Each wait is observed as an event (the sync's wait line), never by elapsed time; the deadline in
_until only turns a hang into a failure.
"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))
import session_index as si  # noqa: E402

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_NOSYSTEM": "1"}
HOLDER = ("import os, sys\nfd = os.open(sys.argv[1], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)\n"
          "print('held', flush=True)\nsys.stdin.readline()\nos.unlink(sys.argv[1])\nprint('unlinked', flush=True)\n")
PATHS = {"modify": "f.txt", "delete": "g.txt"}


def git(cwd, *args, env=None, check=True):
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                       env=dict(os.environ, **(env or {})))
    assert not check or p.returncode == 0, p.stderr
    return p.stdout


def _until(cond, what: str, limit: float = 60.0):
    end = time.monotonic() + limit
    while not cond():
        if time.monotonic() > end:
            pytest.fail(f"never happened: {what}")
        time.sleep(0.05)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for k, v in dict(GIT_ENV, CLAUDE_CODE_SESSION_ID="r14-unit").items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(si, "WAIT_S", 1, raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "f.txt").write_text("one\n")
    (root / "g.txt").write_text("gone\n")
    git(root, "add", "f.txt", "g.txt")
    git(root, "commit", "-qm", "init")
    return root


def commit(root: Path, kind: str) -> str:
    """A commit through this session's private index: f.txt modified, or g.txt the only change, deleted."""
    path = PATHS[kind]
    if kind == "modify":
        (root / path).write_text("two\n")
    else:
        (root / path).unlink()
    env = {"GIT_INDEX_FILE": si.init(str(root))}
    git(root, *(("add", path) if kind == "modify" else ("rm", "-q", "--cached", path)), env=env)
    git(root, "commit", "-qm", "the commit", env=env)
    return path


def shared_is_head(root: Path, path: str) -> bool:
    return git(root, "ls-files", "-s", "--", path).split()[1:2] == git(root, "ls-tree", "HEAD", "--", path).split()[2:3]


def reverted(root: Path, path: str) -> bool:
    return any(line[3:] == path for line in git(root, "status", "--porcelain").splitlines())


@contextlib.contextmanager
def live_holder(lock: Path):
    p = subprocess.Popen([sys.executable, "-c", HOLDER, str(lock)], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "held"
    try:
        yield p
    finally:
        if p.poll() is None:
            p.stdin.write("go\n")
            p.stdin.flush()
            p.wait()


def release(p) -> str:
    p.stdin.write("go\n")
    p.stdin.flush()
    said = p.stdout.readline().strip()
    p.wait()
    return said


def sync_thread(root: Path):
    out, res = io.StringIO(), {}

    def run():
        with contextlib.redirect_stdout(out):
            try:
                res["report"] = si.sync_shared_after_commit(str(root))
            except si.SessionIndexError as e:
                res["error"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, out, res


@pytest.mark.parametrize("kind", ["modify", "delete"])
def test_live_holder_is_waited_for(repo, kind):
    path = commit(repo, kind)
    lock = repo / ".git" / "index.lock"
    with live_holder(lock) as p:
        t, out, res = sync_thread(repo)
        _until(lambda: f"pid {p.pid}" in out.getvalue(), "the wait line naming the holder")
        assert t.is_alive() and lock.exists() and not res and not shared_is_head(repo, path)
        assert release(p) == "unlinked"  # the holder's own lock, untouched until it let go
        t.join(60)
    assert res == {"report": {"synced": [path], "left_foreign": [], "unchanged": []}}
    assert "removed" not in out.getvalue()
    assert shared_is_head(repo, path) and not reverted(repo, path)


@pytest.mark.parametrize("kind", ["modify", "delete"])
def test_git_holding_its_lock_without_a_descriptor_is_waited_for(repo, kind, tmp_path):
    """`git commit -a` in its editor holds index.lock with the descriptor closed: X7 measured option (A)
    removing it; the git process working in the repository keeps it held."""
    path = commit(repo, kind)
    lock = repo / ".git" / "index.lock"
    (repo / "f.txt").write_text("three\n")  # something for `git commit -a` to commit
    fifo = tmp_path / "editor.fifo"
    os.mkfifo(fifo)
    g = subprocess.Popen(["git", "-C", str(repo), "commit", "-a"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         env=dict(os.environ, GIT_EDITOR=f"sh -c 'read x < {fifo}; exit 1'"))
    _until(lock.exists, "git commit -a taking index.lock")
    t, out, res = sync_thread(repo)
    _until(lambda: f"pid {g.pid}" in out.getvalue(), "the wait line naming git")
    assert t.is_alive() and lock.exists() and not res
    fifo.write_text("go\n")
    g.wait()
    t.join(60)
    assert res["report"]["synced"] == [path] and "removed" not in out.getvalue()
    assert shared_is_head(repo, path)


@pytest.mark.parametrize("kind", ["modify", "delete"])
def test_stale_lock_is_removed_once_and_said(repo, kind, capsys):
    path = commit(repo, kind)
    lock = repo / ".git" / "index.lock"
    lock.write_text("")
    os.utime(lock, (time.time() - 60, time.time() - 60))
    report = si.sync_shared_after_commit(str(repo))
    said = capsys.readouterr().out
    assert said.count("SESSION-INDEX: removed") == 1 and str(lock) in said and "WAIT" not in said
    assert report["synced"] == [path] and not lock.exists()
    assert shared_is_head(repo, path) and not reverted(repo, path)


@pytest.mark.parametrize("kind", ["modify", "delete"])
def test_no_lock(repo, kind, capsys):
    path = commit(repo, kind)
    assert si.sync_shared_after_commit(str(repo))["synced"] == [path]
    assert capsys.readouterr().out == ""
    assert not reverted(repo, path)


@pytest.mark.parametrize("kind", ["modify", "delete"])
def test_without_proc_a_stale_lock_is_waited_for_never_removed(repo, kind, tmp_path, monkeypatch):
    path = commit(repo, kind)
    monkeypatch.setattr(si, "_PROC", str(tmp_path / "no-proc"), raising=False)
    lock = repo / ".git" / "index.lock"
    lock.write_text("")
    os.utime(lock, (time.time() - 60, time.time() - 60))
    t, out, res = sync_thread(repo)
    _until(lambda: out.getvalue().count("no /proc") >= 2, "two wait lines")
    assert t.is_alive() and lock.exists() and not res and not shared_is_head(repo, path)
    lock.unlink()  # the test removes it
    t.join(60)
    assert res["report"]["synced"] == [path] and "removed" not in out.getvalue()
    assert not reverted(repo, path)


def test_cli_says_the_removal_before_its_report(repo):
    path = commit(repo, "delete")
    lock = repo / ".git" / "index.lock"
    lock.write_text("")
    os.utime(lock, (time.time() - 60, time.time() - 60))
    p = subprocess.run([sys.executable, str(REPO / "scripts" / "session-index.py"), "sync-shared", "--git-root",
                        str(repo)], capture_output=True, text=True)
    lines = p.stdout.splitlines()
    assert p.returncode == 0 and len(lines) == 2, p
    assert lines[0].startswith("SESSION-INDEX: removed") and f'"synced": ["{path}"]' in lines[1]


def test_linked_worktree_sync_never_meets_the_main_lock(repo, tmp_path):
    """/dev-overnight's --worktree launch: the sync in a linked worktree writes that worktree's own index
    and returns while a live process holds the main index.lock: no wait line, nothing removed."""
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", "-b", "lane", str(wt))
    path = commit(wt, "modify")
    lock = repo / ".git" / "index.lock"
    with live_holder(lock) as p:
        t, out, res = sync_thread(wt)
        t.join(60)
        assert not t.is_alive() and res["report"]["synced"] == [path]
        assert out.getvalue() == "" and lock.exists() and p.poll() is None
        assert release(p) == "unlinked"
    assert shared_is_head(wt, path) and not reverted(wt, path)
