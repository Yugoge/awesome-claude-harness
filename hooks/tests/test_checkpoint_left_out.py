"""A file the private-literal rule names costs only itself, never the whole snapshot.

In the harness home four leftover untracked files holding a listed literal made the rule refuse
every snapshot of the branch for days ("snapshot refused by the private-literal rule: nothing
written"), and the failure counter beside the log read 0. Here, in a throwaway repository with
such files next to ordinary changes, write_checkpoint writes the rest, leaves the offending files
out (a tracked file at HEAD's version) and names them, never a value, in checkpoint.log and in
checkpoint_notice, every time. No listed literal reaches any object of the ref, whether it sits in
an untracked, a tracked, a renamed or a binary file or in a path name. The PII-class exclusion
still runs. The counter of consecutive incomplete snapshots is per repository and ref, and the
notice says since when no complete snapshot exists.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LITERALS = ("acct-test-123", "name-test-456")  # stand-in listed literals (list lines 2 and 3)
REF = "refs/checkpoints/main"


def _git(env: dict, repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], env=env, text=True, capture_output=True, check=True
    ).stdout.strip()


@pytest.fixture
def world(tmp_path: Path) -> tuple[Path, dict]:
    home = tmp_path / "harness"  # the library resolves the engine from its own copy
    shutil.copytree(ROOT / "hooks" / "lib", home / "hooks" / "lib",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (home / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "check-public-core.sh", home / "scripts")
    (tmp_path / "gitconfig").write_text("")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "HOME": str(tmp_path / "user-home"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "config"),
        "CLAUDE_STATE_DIR": str(tmp_path / "state"),
        "CHECKPOINT_LOG_DIR": str(tmp_path / "config" / "logs"),
        "TMPDIR": str(tmp_path / "tmp"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    for key in ("HOME", "CLAUDE_STATE_DIR", "TMPDIR"):
        Path(env[key]).mkdir(parents=True)
    (tmp_path / "config" / "logs").mkdir(parents=True)
    return home, env


def _repo(env: dict, path: Path, files: dict[str, str]) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], env=env, check=True)
    (path / ".gitignore").write_text("/private-literals.txt\n")
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text)
    _git(env, path, "add", "-A")
    _git(env, path, "commit", "-q", "-m", "init")
    return path


def _snapshot(home: Path, env: dict, repo: Path) -> tuple[int, str, str]:
    """One write_checkpoint run: (rc, checkpoint_notice, stderr)."""
    proc = subprocess.run(
        ["bash", "-c", '. "$0"; write_checkpoint "$1" test >/dev/null; rc=$?;'
         ' printf "%s\\n%s" "$rc" "$checkpoint_notice"',
         str(home / "hooks" / "lib" / "checkpoint-core.sh"), str(repo)],
        env=env, text=True, capture_output=True, timeout=120,
    )
    rc, _, notice = proc.stdout.partition("\n")
    return int(rc), notice, proc.stderr


def _log(env: dict) -> str:
    return (Path(env["CLAUDE_CONFIG_DIR"]) / "logs" / "checkpoint.log").read_text()


def _ref_objects_hold_no_literal(env: dict, repo: Path) -> None:
    """Every blob's content and every path name reachable from the ref (all its commits)."""
    listing = _git(env, repo, "rev-list", "--objects", REF)
    assert listing
    for line in listing.splitlines():
        oid, _, path = line.partition(" ")
        assert not any(lit in path for lit in LITERALS), "a path name in the ref holds a literal"
        if _git(env, repo, "cat-file", "-t", oid) == "blob":
            data = subprocess.run(["git", "-C", str(repo), "cat-file", "blob", oid], env=env,
                                  capture_output=True, check=True).stdout
            assert not any(lit.encode() in data for lit in LITERALS), f"blob of {path} holds a literal"


def test_offending_files_are_left_out_and_named_every_time(world, tmp_path: Path) -> None:
    home, env = world
    repo = _repo(env, tmp_path / "project", {
        "README.md": "hello\n",
        "tracked.txt": "clean line\n",
        "to-rename.txt": "renamed content\n",
        "to-rename-2.txt": "clean, renamed onto a listed name\n",
    })
    (repo / "private-literals.txt").write_text("# stand-in list\n" + "\n".join(LITERALS) + "\n")
    # Ordinary changes, next to every kind of offending file.
    (repo / "README.md").write_text("hello, edited\n")
    (repo / "notes.txt").write_text("ordinary note\n")
    (repo / "sessions").mkdir()
    (repo / "sessions" / "s.json").write_text("{}\n")  # a known-PII-class path
    (repo / "leak.txt").write_text(f"ticket for {LITERALS[0]}\n")  # untracked
    (repo / "tracked.txt").write_text(f"clean line\nnow {LITERALS[0]}\n")  # tracked, edited
    (repo / "to-rename.txt").rename(repo / "moved.txt")  # renamed, literal added
    with (repo / "moved.txt").open("a") as fh:
        fh.write(f"and {LITERALS[1]}\n")
    (repo / "to-rename-2.txt").rename(repo / f"dir-{LITERALS[1]}.txt")  # literal in the new name
    (repo / "blob.bin").write_bytes(b"SQLite format 3\x00\x00\xff\x01" + LITERALS[0].encode() + b"\x00\x02")
    named = ["blob.bin", "leak.txt", "moved.txt", "tracked.txt", "<path with private-literals.txt line 3>"]

    first_since = None
    for n in (1, 2):
        rc, notice, _ = _snapshot(home, env, repo)
        assert rc == 0, _log(env)
        head = "Checkpoint snapshot left out 5 file(s) holding a private literal: "
        match = re.fullmatch(re.escape(head) + r"(.*), see logs/checkpoint\.log; no complete snapshot of "
                             + re.escape(REF) + r" since (\S+ \S+) \((\d+) in a row\)", notice)
        assert match, notice
        assert sorted(match.group(1).split(", ")) == sorted(named)
        first_since = first_since or match.group(2)
        assert (match.group(2), int(match.group(3))) == (first_since, n)
        assert _log(env).count("left out 5 file(s) holding a private literal: ") == n
        assert (repo / ".git" / "checkpoint-fail-count.main").read_text().split()[0] == str(n)
        tree = _git(env, repo, "ls-tree", "-r", "--name-only", REF).splitlines()
        assert {"README.md", "notes.txt", "tracked.txt"} <= set(tree)
        assert not {"leak.txt", "moved.txt", "blob.bin", "sessions/s.json"} & set(tree)
        assert not any(LITERALS[1] in p for p in tree)
        assert _git(env, repo, "show", f"{REF}:README.md") == "hello, edited"
        assert _git(env, repo, "show", f"{REF}:tracked.txt") == "clean line"  # HEAD's version
        _ref_objects_hold_no_literal(env, repo)
        with (repo / "notes.txt").open("a") as fh:
            fh.write(f"line {n}\n")
    log = _log(env)
    assert not any(lit in log for lit in LITERALS) and not any(lit in notice for lit in LITERALS)
    assert "hard-excluded 1 known-PII-class path(s) from snapshot" in log

    # A complete snapshot of another project never resets this one's run.
    other = _repo(env, tmp_path / "other", {"a.txt": "a\n"})
    (other / "a.txt").write_text("b\n")
    assert _snapshot(home, env, other)[:2] == (0, "")
    rc, notice, _ = _snapshot(home, env, repo)
    assert rc == 0 and notice.endswith(f"since {first_since} (3 in a row)"), notice

    # Once the offending files are gone the snapshot is complete again and the run ends.
    for rel in ("leak.txt", "blob.bin", "moved.txt", f"dir-{LITERALS[1]}.txt"):
        (repo / rel).unlink()
    _git(env, repo, "checkout", "-q", "--", "tracked.txt")
    assert _snapshot(home, env, repo)[:2] == (0, "")
    assert (repo / ".git" / "checkpoint-fail-count.main").read_text().strip() == "0"
    _ref_objects_hold_no_literal(env, repo)


def test_an_engine_naming_no_path_still_refuses_the_whole_snapshot(world, tmp_path: Path) -> None:
    """Fail closed: what cannot be left out by name refuses the snapshot, as before."""
    home, env = world
    engine = home / "scripts" / "check-public-core.sh"
    engine.write_text(engine.read_text().replace("print path > H", ""))  # no path handed back
    repo = _repo(env, tmp_path / "project", {"README.md": "hello\n"})
    (repo / "private-literals.txt").write_text(f"{LITERALS[0]}\n")
    (repo / "notes.txt").write_text("ordinary note\n")
    (repo / "leak.txt").write_text(f"ticket for {LITERALS[0]}\n")
    rc, notice, _ = _snapshot(home, env, repo)
    assert rc == 3
    assert notice.startswith("Checkpoint snapshot refused by the private-literal rule: nothing written")
    assert notice.endswith("(1 in a row)")
    assert _git(env, repo, "for-each-ref", "refs/checkpoints") == ""
    assert "snapshot refused by the private-literal rule: nothing written" in _log(env)
