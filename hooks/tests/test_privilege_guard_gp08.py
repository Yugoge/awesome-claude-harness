"""The git-privilege guard's one local refusal of force, delete and tag-delete pushes.

A push that forces, deletes or mirrors a ref is refused for every agent, before an
/allow grant or /do consent is consulted; any other push is refused unless /allow
grants it. So each case runs under an /allow grant for `git push`: a push the grant
lets through is one the force/delete rule does not read as a rewrite.

git accepts any unambiguous prefix of a long option and refuses an ambiguous one,
so a prefix of a rewrite option is read as that option.

The guard runs as a subprocess with a scratch HOME, state dir and repository.
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
SID = "gp08-session-0001"
IDENTITY = ("-c", "user.name=sandbox", "-c", "user.email=sandbox@example.invalid")
REWRITE = "BLOCKED: agent git push - force/delete/ref-rewrite push is forbidden."
DEFAULT_DENY = "BLOCKED: agent git push - agents are not authorized to push"

# Refused before /allow and /do: refused on master already, and still refused.
KEPT = [
    "git push --force origin feat",
    "git push -f origin feat",
    "git push --force-with-lease origin feat",
    "git push --force-with-lease=feat origin feat",
    "git push --delete origin feat",
    "git push -d origin feat",
    "git push --mirror origin",
    "git push origin +feat",
    "git push origin +feat:feat",
    "git push origin :feat",
    "git push origin :refs/tags/v1",
    "git push --delete origin v1",
    "git push --delete origin refs/tags/v1",
    "git push origin +refs/tags/v1:refs/tags/v1",
    'bash -c "git push --force origin feat"',
    "timeout 30 git push --force origin feat",
]

# Released by a /allow grant for `git push` on master, refused by this rule now.
EXTENDED = [
    "git push -uf origin feat",                 # clustered short flags
    "git push -fu origin feat",
    "git push -ud origin feat",
    "git push --force-if-includes origin feat",
    "git push --force-with-lease --force-if-includes origin feat",
    "git push --force-w origin feat",           # abbreviated long options
    "git push --force-i origin feat",
    "git push --forc origin feat",
    "git push --del origin feat",
    "git push --dele origin v1",
    "git push --mir origin",
    "git push --m origin",
    "git push --prune origin",
    "git push --pru origin 'refs/heads/*:refs/heads/*'",
    "git push --prune --tags origin",
    "git push origin ':refs/tags/v1'",          # a quoted refspec reads as the shell passes it
    'git push origin "+v1"',
    "git push origin '+refs/tags/v1:refs/tags/v1'",
    "bash -c 'git push -uf origin feat'",       # payloads inside wrappers
    "sh -c 'git push --del origin v1'",
    "env -i git push --forc origin feat",
    "timeout 30 git push --mir origin",
]

# Ordinary publication: the /allow grant lets it through.
ALLOWED = [
    "git push origin feat",
    "git push -u origin feat",
    "git push --set-upstream origin feat",
    "git push --dry-run origin feat",
    "git push -n origin feat",
    "git push --no-force origin feat",
    "git push origin v1",
    "git push origin refs/tags/v1",
    "git push --tags origin",
    "git push --follow-tags origin feat",
    "git push origin feat:refs/heads/feat",
]


class Box:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.state = tmp_path / "state"
        self.repo = tmp_path / "toyproj"
        home = tmp_path / "home"
        for d in (self.state, self.repo, home):
            d.mkdir()
        (home / "gitconfig").write_text("")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
        self.env.update(HOME=str(home), CLAUDE_STATE_DIR=str(self.state),
                        CLAUDE_PROJECT_DIR=str(self.repo), PYTHONDONTWRITEBYTECODE="1",
                        GIT_CONFIG_GLOBAL=str(home / "gitconfig"), GIT_CONFIG_NOSYSTEM="1",
                        GIT_CEILING_DIRECTORIES=str(tmp_path))
        self.git("init", "-q", "-b", "master")
        (self.repo / "README.md").write_text("# toy\n")
        self.git("add", "README.md")
        self.git(*IDENTITY, "commit", "-qm", "init")
        self.git("branch", "feat")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True, env=self.env).stdout

    def grant_push(self) -> Path:
        code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                "from lib.allowlist import write_sentinel_grant; "
                "print(write_sentinel_grant(sys.argv[2], sys.argv[2], "
                "[{'op': 'git', 'target': 'push'}]))")
        out = subprocess.run([sys.executable, "-B", "-c", code, str(HOOKS), SID], check=True,
                             capture_output=True, text=True, env=self.env, cwd=str(self.tmp))
        return Path(out.stdout.strip())

    def run(self, command: str, **payload):
        data = {"session_id": SID, "tool_name": "Bash", "tool_input": {"command": command},
                "cwd": str(self.repo), "hook_event_name": "PreToolUse", **payload}
        return subprocess.run([sys.executable, "-B", str(GUARD)], input=json.dumps(data),
                              text=True, capture_output=True, cwd=str(self.repo), env=self.env,
                              timeout=120)


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


@pytest.mark.parametrize("command", KEPT + EXTENDED)
def test_a_ref_rewriting_push_is_refused_under_an_allow_grant(box, command):
    grant = box.grant_push()
    proc = box.run(command, agent_id="agent-1")
    assert proc.returncode == 2, (command, proc.stderr)
    assert REWRITE in proc.stderr, (command, proc.stderr)
    assert grant.exists(), "the refusal comes before the grant is read"


@pytest.mark.parametrize("command", EXTENDED)
def test_without_a_grant_the_rewrite_rule_names_the_refusal(box, command):
    proc = box.run(command, agent_id="agent-1")
    assert proc.returncode == 2, (command, proc.stderr)
    assert REWRITE in proc.stderr and DEFAULT_DENY not in proc.stderr, (command, proc.stderr)


@pytest.mark.parametrize("command", ALLOWED)
def test_an_allow_grant_lets_an_ordinary_push_through(box, command):
    box.grant_push()
    proc = box.run(command, agent_id="agent-1")
    assert proc.returncode == 0, (command, proc.stderr)


@pytest.mark.parametrize("command", ALLOWED)
def test_an_ordinary_push_without_a_grant_is_refused_as_a_push(box, command):
    proc = box.run(command, agent_id="agent-1")
    assert proc.returncode == 2, (command, proc.stderr)
    assert DEFAULT_DENY in proc.stderr, (command, proc.stderr)


def test_the_push_variable_in_the_hook_environment_authorizes_nothing(box):
    # /push exports it only inside hooks/push.sh, whose own `git push` no hook sees.
    box.env["CLAUDE_PUSH_COMMAND_ACTIVE"] = "1"
    (box.state / f"claude-push-grant-{SID}-0001.json").write_text(json.dumps({
        "branch": "master", "expected_head": box.git("rev-parse", "HEAD").strip(),
        "remote": "origin"}))
    proc = box.run("git push origin master", agent_id="agent-1")
    assert proc.returncode == 2 and DEFAULT_DENY in proc.stderr, proc.stderr


def test_the_variable_written_on_the_command_line_is_judged_as_any_push(box):
    command = "CLAUDE_PUSH_COMMAND_ACTIVE=1 git push origin feat"
    proc = box.run(command, agent_id="agent-1")
    assert proc.returncode == 2 and DEFAULT_DENY in proc.stderr, proc.stderr
    box.grant_push()
    assert box.run(command, agent_id="agent-1").returncode == 0
