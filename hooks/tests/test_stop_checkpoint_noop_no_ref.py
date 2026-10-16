"""A no-op snapshot with no checkpoint ref yet never blocks a Stop (PR 4 review R4, F3).

Drives the registered Stop hook, hooks/stop-workflow-coordinator.py with its four default
phases, and hooks/auto-commit.sh itself, in a throwaway copy of the harness home with the
claude-settings filter registered as init registers it. The only change is a CLI-only
settings.json write: git status reports the file modified (its size changed), but the clean
form drops the key, so the snapshot tree equals HEAD's and write_checkpoint creates no ref.
auto-commit.sh then exits 0 and prints no tip, and the Stop passes with and without
stop_hook_active, on a branch and on a detached HEAD. A real change is still snapshotted and
its tip printed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SID = "sess-r4-test"
PHASES = ["timelock", "coverage", "auto_commit", "cleanup"]
SETTINGS = {"permissions": {"allow": ["Bash(git status:*)"]}}


def _git(env: dict, repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], env=env, text=True, capture_output=True, check=check
    ).stdout.strip()


@pytest.fixture(params=["branch", "detached"])
def harness(request, tmp_path: Path) -> tuple[Path, dict, str]:
    home = tmp_path / "harness"
    shutil.copytree(
        ROOT / "hooks", home / "hooks", ignore=shutil.ignore_patterns("tests", "__pycache__")
    )
    engine = "scripts/install/render-settings"  # the claude-settings filter
    (home / engine).parent.mkdir(parents=True)
    shutil.copy2(ROOT / engine, home / engine)
    (home / ".gitignore").write_text("/settings.machine.json\n/private-literals.txt\n")
    (home / ".gitattributes").write_text("/settings.json filter=claude-settings\n")
    (home / "settings.json").write_text(json.dumps(SETTINGS, indent=2) + "\n")
    (tmp_path / "gitconfig").write_text("")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "HOME": str(tmp_path / "user-home"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "config"),
        "CLAUDE_STATE_DIR": str(tmp_path / "state"),
        "TMPDIR": str(tmp_path / "tmp"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    for key in ("HOME", "CLAUDE_STATE_DIR", "TMPDIR"):
        Path(env[key]).mkdir(parents=True)
    (tmp_path / "config" / "logs").mkdir(parents=True)  # an installed home has its logs/
    subprocess.run(["git", "init", "-q", "-b", "main", str(home)], env=env, check=True)
    for key, value in (  # as scripts/bootstrap registers the filter
        ("clean", "python3 scripts/install/render-settings clean"),
        ("smudge", "python3 scripts/install/render-settings smudge"),
        ("required", "true"),
    ):
        _git(env, home, "config", f"filter.claude-settings.{key}", value)
    _git(env, home, "add", "-A")
    _git(env, home, "commit", "-q", "-m", "init")
    if request.param == "detached":
        _git(env, home, "checkout", "-q", "--detach")
        ref = f"refs/checkpoints/detached-{_git(env, home, 'rev-parse', '--short', 'HEAD')}"
    else:
        ref = "refs/checkpoints/main"
    # A CLI-only write (Claude Code's /theme): the clean form drops the key.
    (home / "settings.json").write_text(json.dumps({**SETTINGS, "theme": "dark"}, indent=2) + "\n")
    assert _git(env, home, "status", "--porcelain") == "M settings.json"
    assert subprocess.run(["git", "-C", str(home), "diff", "--quiet"], env=env).returncode == 0
    assert _git(env, home, "for-each-ref", "refs/checkpoints") == ""
    return home, env, ref


def _auto_commit(home: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(home / "hooks" / "auto-commit.sh")],
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        cwd=str(home),
        env={**env, "CLAUDE_PROJECT_DIR": str(home)},
        timeout=120,
    )


def _stop(home: Path, env: dict, *, active: bool) -> dict:
    """One Stop event through the registered hook, as Claude Code sends it."""
    flag = Path(env["CLAUDE_STATE_DIR"]) / f"claude-orchestrator-consent-{SID}.flag"
    flag.write_text("granted\n")  # the cleanup phase removes it
    payload = {
        "session_id": SID,
        "transcript_path": str(home / "transcript.jsonl"),
        "cwd": str(home),
        "hook_event_name": "Stop",
        "stop_hook_active": active,
    }
    proc = subprocess.run(
        [sys.executable, str(home / "hooks" / "stop-workflow-coordinator.py")],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(home),
        env={**env, "CLAUDE_PROJECT_DIR": str(home)},
        timeout=300,
    )
    return {
        "rc": proc.returncode,
        "raw": proc.stdout + proc.stderr,
        "out": json.loads(proc.stdout),
        "cleanup_ran": not flag.exists(),
    }


def test_no_op_snapshot_without_a_ref_never_blocks_a_stop(harness) -> None:
    home, env, ref = harness
    commits_before = _git(env, home, "rev-list", "--all", "--count")
    for active in (False, True):
        stop = _stop(home, env, active=active)
        out = stop["out"]
        assert stop["rc"] == 0, stop["raw"]
        assert out["status"] == "pass" and "failed_phase" not in out, out
        assert [p["phase"] for p in out["phases"]] == PHASES
        assert all(p["status"] == "allow" for p in out["phases"]), out
        assert stop["cleanup_ran"], "the cleanup phase did not run"
        assert "systemMessage" not in out
    assert _git(env, home, "for-each-ref", "refs/checkpoints") == "", f"no-op wrote {ref}"
    assert _git(env, home, "rev-list", "--all", "--count") == commits_before


def test_auto_commit_prints_no_tip_until_a_snapshot_is_written(harness) -> None:
    home, env, ref = harness
    noop = _auto_commit(home, env)
    assert noop.returncode == 0, noop.stdout + noop.stderr
    assert f"Ref: {ref}" in noop.stdout and "Tip:" not in noop.stdout
    assert _git(env, home, "for-each-ref", "refs/checkpoints") == ""

    (home / "notes.txt").write_text("ordinary note\n")
    real = _auto_commit(home, env)
    assert real.returncode == 0, real.stdout + real.stderr
    tip = _git(env, home, "rev-parse", "--short", ref)
    assert f"Tip: {tip}" in real.stdout
    assert _git(env, home, "show", f"{ref}:notes.txt") == "ordinary note"
    assert "theme" not in _git(env, home, "show", f"{ref}:settings.json")
