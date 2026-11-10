"""The privilege guard's commit refusal names routes a human can take in the harness.

P9-5 (owner ruling D19): no step may send the owner to his own shell. The commit refusal
once said "exit the agent context and run git commit directly"; the real routes are
/commit (or /allow git commit for one call). The test runs the real hook as a subprocess,
in a scratch HOME, state dir and repository, and reads its stderr. The exit code stays 2.

The PUSH refusal text is pinned UNCHANGED, on purpose: .github/assets/hero-capture.txt and
guard-hero.json quote it ("For human-driven push, exit the agent context and run git push
directly.") and scripts/verify-hero-provenance.py:51 anchors it. Changing it needs the hero
capture regenerated, which is work outside the security group's files; until then the text
stays byte for byte as it was.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "hooks" / "pretool-git-privilege-guard.py"
IDENTITY = ("-c", "user.name=sandbox", "-c", "user.email=sandbox@example.invalid")

# The commit advice that sent the owner to his own shell.
OLD_COMMIT_ADVICE = ("exit the agent context and run git commit directly", "git commit directly",
                     "own shell")
# The push refusal's remedy line, pinned unchanged (see the module docstring).
PUSH_REMEDY = ("For human-driven push, exit the agent context and run git push directly.\n")


@pytest.fixture
def run_guard(tmp_path):
    home, state, repo = tmp_path / "home", tmp_path / "state", tmp_path / "toyproj"
    for d in (home, state, repo):
        d.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_", "PYTHON"))}
    env.update(HOME=str(home), CLAUDE_STATE_DIR=str(state), CLAUDE_PROJECT_DIR=str(repo),
               PYTHONDONTWRITEBYTECODE="1", GIT_CEILING_DIRECTORIES=str(tmp_path),
               GIT_CONFIG_NOSYSTEM="1")

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)

    git("init", "-q", "-b", "master")
    (repo / "README.md").write_text("# toy\n")
    git("add", "README.md")
    git(*IDENTITY, "commit", "-qm", "init")

    def run(command):
        payload = {"session_id": "refusal-routes-0001", "tool_name": "Bash",
                   "tool_input": {"command": command}, "cwd": str(repo),
                   "hook_event_name": "PreToolUse", "transcript_path": "",
                   "permission_mode": "default"}
        return subprocess.run([sys.executable, "-B", str(GUARD)], input=json.dumps(payload),
                              text=True, capture_output=True, cwd=str(repo), env=env, timeout=120)

    return run


def test_a_refused_commit_names_commit_and_allow_git_commit(run_guard):
    proc = run_guard("git commit -m 'feat: sandbox change'")
    assert proc.returncode == 2, proc.stderr
    assert "BLOCKED: agent git commit" in proc.stderr
    assert "a human types /commit (or /allow git commit for one call)" in proc.stderr
    for old in OLD_COMMIT_ADVICE:
        assert old not in proc.stderr, (old, proc.stderr)


@pytest.mark.parametrize("command", ["git push", "git push origin master"])
def test_the_push_refusal_text_is_unchanged(run_guard, command):
    # Quoted by the hero capture and anchored at scripts/verify-hero-provenance.py:51.
    proc = run_guard(command)
    assert proc.returncode == 2, proc.stderr
    assert "BLOCKED: agent git push" in proc.stderr
    assert PUSH_REMEDY in proc.stderr, proc.stderr


def test_the_module_docstring_does_not_send_the_owner_to_his_shell():
    text = GUARD.read_text()
    for old in OLD_COMMIT_ADVICE:
        assert old not in text, old
