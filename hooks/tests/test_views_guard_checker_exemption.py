#!/usr/bin/env python3
"""The views / cp-state guard exempts the command that runs spec-check.py, not a command line that
names it (hardcode audit 2026-11-19, finding 12).

hooks/pretool-bash-views-guard.py searched the whole command text for the checker's path and
exited 0 on a match, so a comment, an `ls` of the script or a `:` with its name let any redirect
into a cp-state file or a view through. The exemption is now the checker's own simple command
(the script run by name, or as python's first argument): its words and redirections are not read,
every other command of the line is read as it is alone.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-bash-views-guard.py"
SPEC_CHECK = ROOT / "scripts" / "spec-check.py"
CHANNEL = '"${CLAUDE_HOME:-$HOME/.claude}/scripts/spec-check.py"'
CP_STATE = ".claude/specs/s1/cp-state-dev.json"
VIEW = "docs/dev/specs/s1/views/dev.md"

NAMED_NOT_RUN = [  # the checker's name is in the text; the command that writes is not the checker
    f"printf '{{}}' > {CP_STATE}  # .claude/scripts/spec-check.py",
    f"ls .claude/scripts/spec-check.py; printf '{{}}' > {CP_STATE}",
    f"printf '{{}}' > {CP_STATE}; : bin/spec-check.py",
    f"cat .claude/scripts/spec-check.py > {CP_STATE}",
    f"echo {CHANNEL} > {VIEW}",
    f"python3 -c \"print(1)\" .claude/scripts/spec-check.py > {CP_STATE}",
    f"python3 -u -m json.tool .claude/scripts/spec-check.py > {CP_STATE}",
]
RUN_BESIDE_A_WRITE = [  # the checker does run; another command of the same line writes
    f"echo x > {VIEW} && python3 ~/.claude/scripts/spec-check.py status --spec-id s1",
    f"python3 {CHANNEL} status --spec-id s1; printf '{{}}' > {CP_STATE}",
    f"python3 ~/.claude/scripts/spec-check.py status --spec-id s1 | tee {CP_STATE}",
    f"{{ python3 ~/.claude/scripts/spec-check.py status --spec-id s1; }} > {CP_STATE}",
    f"python3 {CHANNEL} status --spec-id \"$(printf '{{}}' > {CP_STATE})\"",
    f"python3 {CHANNEL} mark --spec-id s1 --agent dev --agent-id a1 --cp-id cp-01 && cp /tmp/a.md {VIEW}",
    f"python3 {CHANNEL} status --spec-id s1 && echo 'next -> {VIEW}'",  # the echo, read as it is alone
]
CHECKER_RUNS = [  # the legal writer, in the spellings the commands and agents use
    f"python3 {CHANNEL} mark --spec-id s1 --agent dev --agent-id a1 --cp-id cp-01",
    f"python3 {CHANNEL} checkpoints --spec-id s1 --agent dev --agent-id a1 --action \"Write the dev view -> {VIEW}\"",
    f"source \"${{CLAUDE_HOME:-$HOME/.claude}}/venv/bin/activate\" && python3 {CHANNEL} checkpoints \\\n"
    f"    --spec-id s1 --agent dev --agent-id a1 \\\n    --action \"Write the dev view -> {VIEW}\"",
    f"python3 ~/.claude/scripts/spec-check.py checkpoints --spec-id s1 --agent dev --agent-id a1 --action 'x -> {VIEW}'",
    f"timeout 30 python3.12 ~/.claude/scripts/spec-check.py status --spec-id s1 --note '-> {VIEW}' 2>&1 | tail -3",
    f"~/.claude/scripts/spec-check.py checkpoints --spec-id s1 --agent dev --agent-id a1 --action '-> {VIEW}'",
    f"python3 bin/spec-check.py checkpoints --spec-id s1 --agent dev --agent-id a1 --action '-> {VIEW}'",
    f"python3 ~/.claude/scripts/spec-check.py mark --spec-id s1 --agent dev --agent-id a1 --cp-id cp-01 > {CP_STATE}",
    f"python3 {CHANNEL} status --spec-id s1 && echo done > notes.txt",
    f"python3 -u ~/.claude/scripts/spec-check.py checkpoints --spec-id s1 --agent dev --agent-id a1 --action 'x -> {VIEW}'",
    f"python3 -uB {CHANNEL} checkpoints --spec-id s1 --agent dev --agent-id a1 --action \"x -> {VIEW}\"",
]


def _decide(command: str, cwd: Path) -> subprocess.CompletedProcess:
    payload = {"tool_name": "Bash", "session_id": "views-guard-checker", "cwd": str(cwd),
               "tool_input": {"command": command}}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True, capture_output=True,
                          cwd=str(cwd), check=False, timeout=60)


@pytest.fixture
def proj(tmp_path):
    (tmp_path / ".claude" / "specs" / "s1").mkdir(parents=True)
    (tmp_path / "docs" / "dev" / "specs" / "s1" / "views").mkdir(parents=True)
    return tmp_path


@pytest.mark.parametrize("command", NAMED_NOT_RUN + RUN_BESIDE_A_WRITE)
def test_naming_the_checker_exempts_no_other_command(proj, command):
    result = _decide(command, proj)
    assert result.returncode == 2 and "BLOCKED: Bash write-bypass into views/cp-state" in result.stderr, command


@pytest.mark.parametrize("command", CHECKER_RUNS)
def test_the_command_that_runs_the_checker_passes(proj, command):
    result = _decide(command, proj)
    assert result.returncode == 0 and not result.stderr, (command, result.stderr)


def test_the_checker_really_writes_a_cp_state_file_through_the_guard(proj):
    """The guard passes the two calls agents/spec.md gives, and running them writes the slot."""
    env = {**os.environ, "CLAUDE_HOME": str(ROOT), "CLAUDE_PROJECT_DIR": str(proj)}
    slot = proj / ".claude" / "specs" / "s1" / "cp-state-dev.json"
    for args in ("check-in --spec-id s1 --agent dev --agent-id a1",
                 f"checkpoints --spec-id s1 --agent dev --agent-id a1 --action \"Write the dev view -> {VIEW}\""):
        command = f"{sys.executable} {CHANNEL} {args}"
        assert _decide(command, proj).returncode == 0, command
        ran = subprocess.run(["bash", "-c", command], cwd=str(proj), env=env, capture_output=True, text=True,
                             timeout=60)
        assert ran.returncode == 0, ran.stderr
    state = json.loads(slot.read_text())
    assert state["agent_id"] == "a1" and [c["action"] for c in state["checkpoints"]] == [f"Write the dev view -> {VIEW}"]
    # the same file, written by anything but the checker, stays refused
    assert _decide(f"printf '{{}}' > {slot}", proj).returncode == 2
