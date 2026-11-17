"""A command word whose expansion is only in its directory part is not git (OB-L25).

`"$VIRTUAL_ENV/bin/pip" show pytest` runs pip wherever the variable points:
each expansion is a plain variable inside double quotes, so it is one field,
never split or globbed, and the literal `/pip` after the last one fixes the
file name. The guard reads it as it reads a literal path ending in that name.

Still refused (residual `dynamic_git_token`, or a git invocation):
  - an expansion in the file name (`$GIT push`, `${G}it commit`, `"$X/bin/$Y" push`);
  - a parameter operator, whatever its default (`G=git; ${G:-kubectl} push`),
    `$@`, and a substitution in the word (`"$(pwd)/bin/pip"`);
  - an unquoted expansion (`$D/bin/pip show`): its value may split into
    `/usr/bin/git push origin master #`, whose first field is git;
  - a glob or brace in the word, a `$'..'` or `$".."` piece;
  - a git-like file name: `git` (a git invocation), `GIT`, `git-*`, `hub`.

The guard runs as a subprocess with a scratch HOME, state dir and repository,
with a main-agent payload and a subagent payload.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
GUARD = HOOKS / "pretool-git-privilege-guard.py"
sys.path.insert(0, str(HOOKS))

from lib.git_command_classifier import classify_git_command  # noqa: E402

MUST_PASS = [
    '"$VIRTUAL_ENV/bin/pip" show pytest',
    '"$CLAUDE_HOME/scripts/session-index.py" init',
    '"$HOME/bin/helm" status myrelease',
    '"${HOME}/bin/helm" status myrelease',
    '"$X"/bin/pip show pytest',
    'sudo "$HOME/bin/helm" status myrelease',
    'cd /tmp && "$VIRTUAL_ENV/bin/pip" show pytest',
]

MUST_REFUSE = [
    "$GIT push",
    "${G}it commit",
    "G=git; ${G:-kubectl} push origin master",
    '"$X/bin/$Y" push',
    '"$X/bin/"$Y push',
    "$D/bin/pip push origin master",
    '"$X/bin/git" push origin master',
    '"$X/bin/GIT" push origin master',
    '"$X/bin/Git" push origin master',
    '"$X/bin/git-receive-pack" push',
    '"$X/bin/git-push" push',
    '"$X/bin/hub" push origin master',
    '"$X/bin/"\\git push origin master',
    "\"$X/bin/g\"'it' push origin master",
    "\"$X\"/bin/$'git' push origin master",
    '$"$X/bin/pip" push',
    '"$(pwd)/bin/pip" push',
    '"`pwd`/bin/pip" push',
    '"${X:-$(git push)}/bin/pip" show',
    '"${X:-/usr/bin/git}" push',
    '"$@/bin/pip" push',
    '"$X"/bin/{git,x} push',
    '"$X"/bin/gi? push',
    '"$X"/*/pip push',
    '"$X/" push',
    '"$X/.." push',
]


def _found(command):
    invocations, residuals = classify_git_command(command)
    return [inv.subcommand for inv in invocations], residuals


@pytest.mark.parametrize("command", MUST_PASS)
def test_an_expansion_in_the_directory_is_not_git(command):
    found, residuals = _found(command)
    assert found == [] and residuals == [], (found, residuals)


@pytest.mark.parametrize("command", MUST_REFUSE)
def test_a_word_that_may_name_git_is_still_read(command):
    found, residuals = _found(command)
    assert found or residuals, command


def _sandbox(tmp_path):
    home, state, repo = (tmp_path / n for n in ("home", "state", "proj"))
    for d in (home, state, repo):
        d.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_", "PYTHON"))}
    env.update(HOME=str(home), CLAUDE_STATE_DIR=str(state), CLAUDE_PROJECT_DIR=str(repo),
               PYTHONDONTWRITEBYTECODE="1", GIT_CEILING_DIRECTORIES=str(tmp_path),
               GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True, env=env,
                   capture_output=True)
    return repo, env


def _run(command, repo, env, subagent):
    payload = {"session_id": "dyn-dir-0001", "tool_name": "Bash",
               "tool_input": {"command": command}, "cwd": str(repo),
               "hook_event_name": "PreToolUse", "transcript_path": "",
               "permission_mode": "default"}
    if subagent:
        payload.update(agent_id="agent-dyn-dir", agent_type="general-purpose")
    return subprocess.run([sys.executable, "-B", str(GUARD)], input=json.dumps(payload),
                          text=True, capture_output=True, cwd=str(repo), env=env, timeout=120)


@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_the_guard_lets_a_dynamic_directory_through(tmp_path, subagent):
    repo, env = _sandbox(tmp_path)
    for command in MUST_PASS:
        proc = _run(command, repo, env, subagent)
        assert proc.returncode == 0, (command, proc.stderr)


@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_the_guard_still_refuses_a_dynamic_git_word(tmp_path, subagent):
    repo, env = _sandbox(tmp_path)
    for command in MUST_REFUSE:
        proc = _run(command, repo, env, subagent)
        assert proc.returncode == 2, (command, proc.stdout, proc.stderr)
        assert "BLOCKED" in proc.stderr, (command, proc.stderr)
