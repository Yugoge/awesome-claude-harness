"""A checkpoint snapshot of a large project fits its time limit, and one that still runs past it says so.

Live, a project with a few hundred tracked files and some 1,700 untracked ones (about 260 MB, none ignored) had no
snapshot for most of a day: every snapshot seeded a fresh index from HEAD's tree, which has no stat data, so
`git add -A` read and hashed every tracked and untracked file again, and a shell loop then walked the whole index
once more; on a loaded host that ran past the pre-command hook's 10 s, which ended it and logged nothing.
Here, in throwaway projects: the second snapshot hashes only what changed since the first (counted by a clean
filter, never by the clock), its tree is the one a seed from HEAD gives, and a snapshot ended at its bound
leaves a log line with its duration and its cause and a notice that says so; the pre-command hook's own ending
is logged too.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REF = "refs/checkpoints/main"

_SNAP = r'''. "$1/hooks/lib/checkpoint-core.sh" || exit 90; export CHECKPOINT_NO_PUSH=1
write_checkpoint "$2" "test"; rc=$?
printf '%s\n' "$rc" "$checkpoint_commit" "$checkpoint_late" "$checkpoint_notice"'''


@pytest.fixture
def world(tmp_path: Path) -> tuple[Path, dict]:
    home = tmp_path / "harness"
    shutil.copytree(ROOT / "hooks" / "lib", home / "hooks" / "lib", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "gitconfig").write_text("")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8",
           "HOME": str(tmp_path / "user-home"), "CLAUDE_CONFIG_DIR": str(tmp_path / "config"),
           "CLAUDE_STATE_DIR": str(tmp_path / "state"), "TMPDIR": str(tmp_path / "tmp"),
           "CHECKPOINT_LOG_DIR": str(tmp_path / "logs"), "GIT_CEILING_DIRECTORIES": str(tmp_path),
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
           "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    for key in ("HOME", "CLAUDE_STATE_DIR", "TMPDIR", "CHECKPOINT_LOG_DIR"):
        Path(env[key]).mkdir(parents=True)
    return home, env


def _git(env: dict, repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], env=env, text=True, capture_output=True,
                          check=True).stdout.strip()


def _snap(world, repo: Path, extra: dict | None = None) -> dict:
    home, env = world
    p = subprocess.run(["bash", "-c", _SNAP, "snap", str(home), str(repo)], env={**env, **(extra or {})},
                       text=True, capture_output=True, timeout=120)
    rc, commit, late, notice = (p.stdout.split("\n", 3) + [""] * 4)[:4]
    return {"rc": rc, "commit": commit, "late": late, "notice": notice.strip(), "stderr": p.stderr}


def _age(repo: Path) -> None:
    """Every work tree file 100 s old, so no index entry is racily clean (git would hash it again, rightly)."""
    past = time.time() - 100
    for d, _, files in os.walk(repo):
        if "/.git" in d + "/" and ".git" in Path(d).parts:
            continue
        for f in files:
            os.utime(os.path.join(d, f), (past, past))


def _counting_project(env: dict, repo: Path, count: Path) -> None:
    """The live shape: tracked files, many untracked files that nothing ignores, an ignored directory and the scratch
    root. A clean filter on every file appends one line to `count` each time git hashes a file."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], env=env, check=True)
    _git(env, repo, "config", "filter.count.clean", f"sh -c 'echo x >>\"{count}\"; cat'")
    (repo / ".gitattributes").write_text("* filter=count\n")
    (repo / ".gitignore").write_text("node_modules/\n")
    for i in range(20):
        (repo / f"t{i}.txt").write_text(f"tracked {i}\n")
    _git(env, repo, "add", "-A")
    _git(env, repo, "commit", "-q", "-m", "init")
    (repo / "reports" / "run").mkdir(parents=True)
    for i in range(60):
        (repo / "reports" / "run" / f"r{i}.json").write_text(f"report {i}\n")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "dep.js").write_text("ignored\n")
    (repo / ".claude" / "scratch" / "s").mkdir(parents=True)
    (repo / ".claude" / "scratch" / "s" / "tmp.txt").write_text("scratch\n")
    _age(repo)


def _hashed(count: Path) -> int:
    return len(count.read_text().splitlines()) if count.exists() else 0


def test_a_second_snapshot_hashes_only_what_changed_since_the_first(world, tmp_path):
    home, env = world
    repo, count = tmp_path / "proj", tmp_path / "count"
    _counting_project(env, repo, count)
    first = _snap(world, repo)
    assert first["rc"] == "0" and first["commit"], first
    after_first = _hashed(count)
    assert after_first >= 60, after_first  # the untracked files were read once
    (repo / "reports" / "run" / "r0.json").write_text("changed\n")
    past = time.time() - 50
    os.utime(repo / "reports" / "run" / "r0.json", (past, past))
    second = _snap(world, repo)
    assert second["rc"] == "0" and second["commit"] != first["commit"], second
    # Only the changed file is read again; a seed with no stat data read all 80 (20 tracked, 60 untracked).
    assert _hashed(count) - after_first <= 2, _hashed(count) - after_first
    tree = _git(env, repo, "ls-tree", "-r", "--name-only", second["commit"]).splitlines()
    assert "reports/run/r0.json" in tree and "t0.txt" in tree and len(tree) == 20 + 60 + 2
    assert not any(p.startswith(("node_modules/", ".claude/scratch/")) for p in tree), tree
    assert _git(env, repo, "show", f"{second['commit']}:reports/run/r0.json") == "changed"


def _tree(env, repo, commit):
    return _git(env, repo, "rev-parse", f"{commit}^{{tree}}")


def test_a_seed_from_the_last_snapshot_gives_the_tree_a_seed_from_head_gives(world, tmp_path):
    """What the last snapshot held and a seed from HEAD would not: a file ignored since, a file deleted since, and a
    HEAD that moved on (a commit with a file forced past an ignore rule). Each snapshot's tree is compared with the
    one the same library writes with no earlier snapshot to seed from."""
    home, env = world
    repo = tmp_path / "proj"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], env=env, check=True)
    (repo / "a.txt").write_text("a\n")
    _git(env, repo, "add", "-A")
    _git(env, repo, "commit", "-q", "-m", "init")
    (repo / "later-ignored.log").write_text("x\n")
    (repo / "gone.txt").write_text("y\n")
    (repo / "keep.txt").write_text("z\n")
    assert _snap(world, repo)["rc"] == "0"
    cache = repo / ".git" / "checkpoint-stat-index"
    assert cache.is_file()
    (repo / ".gitignore").write_text("*.log\nforced.bin\n")
    (repo / "gone.txt").unlink()
    (repo / "forced.bin").write_text("f\n")
    _git(env, repo, "add", "-f", "forced.bin", ".gitignore")
    _git(env, repo, "commit", "-q", "-m", "two")
    seeded = _snap(world, repo)
    assert seeded["rc"] == "0", seeded
    names = _git(env, repo, "ls-tree", "-r", "--name-only", seeded["commit"]).splitlines()
    assert sorted(names) == [".gitignore", "a.txt", "forced.bin", "keep.txt"], names
    cache.unlink()
    (repo / "keep.txt").write_text("z2\n")  # a new tree, so the fresh one is written and not a no-op
    fresh = _snap(world, repo)
    assert cache.is_file()
    (repo / "keep.txt").write_text("z\n")
    again = _snap(world, repo)
    assert _tree(env, repo, again["commit"]) == _tree(env, repo, seeded["commit"])
    assert _git(env, repo, "ls-tree", "-r", "--name-only", fresh["commit"]).splitlines() == names


def _slow(env: dict, repo: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], env=env, check=True)
    (repo / "a.txt").write_text("a\n")
    _git(env, repo, "add", "-A")
    _git(env, repo, "commit", "-q", "-m", "init")
    _git(env, repo, "config", "filter.slow.clean", "sleep 30; cat")
    (repo / ".gitattributes").write_text("*.txt filter=slow\n")
    (repo / "b.txt").write_text("b\n")


def test_a_snapshot_ended_at_its_bound_is_logged_with_its_duration_and_cause_and_says_so(world, tmp_path):
    home, env = world
    repo = tmp_path / "proj"
    _slow(env, repo)
    shot = _snap(world, repo, {"CHECKPOINT_SCAN_TIMEOUT": "1"})
    assert shot["rc"] == "1" and shot["late"] == "1", shot
    assert re.match(r"Checkpoint snapshot ran past its time limit after \d+s \(git add -A was ended at its bound, "
                    r"CHECKPOINT_SCAN_TIMEOUT=1s\): nothing written, see logs/checkpoint.log; no complete snapshot",
                    shot["notice"]), shot
    log = (Path(env["CHECKPOINT_LOG_DIR"]) / "checkpoint.log").read_text()
    assert re.search(r"\[ERROR\] snapshot ran past its time limit after \d+s: git add -A was ended at its bound, "
                     r"CHECKPOINT_SCAN_TIMEOUT=1s; nothing written \(ref=refs/checkpoints/main, repo=", log), log
    assert _git(env, repo, "for-each-ref", "refs/checkpoints") == ""


_PRE = r"""
import json, os, sys
sys.path[:0] = [os.path.join(sys.argv[1], "lib"), sys.argv[1]]  # argv[1]: the hooks directory, as the hook's own
import bash_safety_rules as R
print(json.dumps(R.snapshot_before({"cwd": sys.argv[2]})))
"""


def test_a_snapshot_the_pre_command_hook_ends_is_logged_and_the_line_says_so(world, tmp_path):
    home, env = world
    repo = tmp_path / "proj"
    _slow(env, repo)
    p = subprocess.run([sys.executable, "-c", _PRE, str(home / "hooks"), str(repo)], text=True, capture_output=True,
                       env={**env, "CLAUDE_HOOK_SNAPSHOT_TIMEOUT": "1s"}, timeout=120)
    assert p.stdout.strip(), p.stderr
    shot = json.loads(p.stdout)
    assert shot == {"none": "the snapshot took longer than 1 s (CLAUDE_HOOK_SNAPSHOT_TIMEOUT) and was ended; "
                            "logged in logs/checkpoint.log"}, (shot, p.stderr)
    log = (Path(env["CHECKPOINT_LOG_DIR"]) / "checkpoint.log").read_text()
    assert re.search(r"\[ERROR\] snapshot ran past its time limit after 1s: ended by the pre-command hook at "
                     r"CLAUDE_HOOK_SNAPSHOT_TIMEOUT; nothing written \(ref=\?, repo=" + re.escape(str(repo)), log), log


def test_the_stop_hook_line_says_the_snapshot_ran_past_its_time_limit(world, tmp_path):
    home, env = world
    shutil.copy2(ROOT / "hooks" / "auto-commit.sh", home / "hooks" / "auto-commit.sh")
    repo = tmp_path / "proj"
    _slow(env, repo)
    p = subprocess.run(["bash", str(home / "hooks" / "auto-commit.sh")], cwd=repo, text=True, capture_output=True,
                       env={**env, "CHECKPOINT_SCAN_TIMEOUT": "1", "CHECKPOINT_NO_PUSH": "1"}, timeout=120)
    assert p.returncode == 1, (p.stdout, p.stderr)
    assert re.search(r"Checkpoint failed: Checkpoint snapshot ran past its time limit after \d+s \(git add -A was "
                     r"ended at its bound, CHECKPOINT_SCAN_TIMEOUT=1s\)", p.stdout), p.stdout
