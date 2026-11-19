"""Option tables of ordinary programs are one definition each (hooks/lib/shell_parse.py), read by every guard.

- ripgrep: the options whose value is a program it runs (RG_PROGRAM_OPTS: --pre, --hostname-bin) and
  every option that makes it run one (RG_RUN_OPTS, adding --search-zip). The git command classifier
  knew only --pre, so `rg --hostname-bin '<git command>'` passed the git privilege guard that every
  other guard refused.
- awk: the options that take a value, by what the value is (AWK_DATA_OPTS, AWK_SOURCE_OPTS,
  AWK_PROGFILE_OPTS, AWK_LIB_OPTS). The removal analyzer skipped only -f/--file/-v/--assign, so the
  program attached as `--source=PROG` was not read and `awk --source='BEGIN{system("rm -rf build")}'`
  passed the bash safety hook that refused `awk --source 'PROG'`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS / "lib"))
import git_command_classifier  # noqa: E402
sys.path.pop(0)


def _hook(name: str, command: str, project: Path) -> int:
    home = project.parent / "home"
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
               "cwd": str(project), "session_id": "options", "transcript_path": str(project / "t.jsonl"),
               "permission_mode": "default", "tool_use_id": "toolu_options"}
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "CODEX", "GIT_"))}
    env.update(HOME=str(home), CLAUDE_PROJECT_DIR=str(project), CLAUDE_CONFIG_DIR=str(home / ".claude"),
               CLAUDE_STATE_DIR=str(home / "state"))
    interp = [sys.executable] if name.endswith(".py") else ["bash"]
    return subprocess.run(interp + [str(HOOKS / name)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(project), env=env, timeout=120).returncode


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("options")
    p = root / "proj"
    for d in ("src", "build"):
        (p / d).mkdir(parents=True)
    (root / "home" / ".claude").mkdir(parents=True)
    (root / "home" / "state").mkdir()
    return p


@pytest.mark.parametrize("command", ["rg --pre 'git commit -m x' x .", "rg --hostname-bin 'git commit -m x' x .",
                                     "rg --hostname-bin='git commit -m x' x ."])
def test_the_git_guard_reads_every_rg_option_that_runs_a_program(project, command):
    assert [(i.cmd_token, i.subcommand) for i in git_command_classifier.iter_git_invocations(command)] == [
        ("git", "commit")]
    assert _hook("pretool-git-privilege-guard.py", command, project) == 2


@pytest.mark.parametrize("command", ["awk --source 'BEGIN{system(\"rm -rf build\")}'",
                                     "awk --source='BEGIN{system(\"rm -rf build\")}'",
                                     "awk -e 'BEGIN{system(\"rm -rf build\")}'"])
def test_the_removal_analyzer_reads_every_awk_program_option(project, command):
    assert _hook("pretool-bash-safety.sh", command, project) == 2


def test_a_plain_awk_read_stays_free(project):
    assert _hook("pretool-bash-safety.sh", "awk -F: -v x=1 '{print $1}' /etc/hostname", project) == 0
