"""The git-privilege guard lets the read-only forms of a guarded subcommand through.

Its rules judge an invocation by its subcommand name, so help (`git push --help`,
`git --help push`, `git merge -h`), a dry run (`git push -n|--dry-run`,
`git commit --dry-run`) and `git rebase|am --show-current-patch` were refused as a
push, a commit or plumbing. Each is now read on its own, so a read-only form
next to a real operation still meets the operation's rule, and only a form the
command cannot reconfigure is read-only: help runs help.browser, man.viewer or a
pager, and a push dry run a transport, all of which configuration can name.

commit's `-n` is --no-verify, never a dry run.

The guard runs as a subprocess with a scratch HOME, state dir and repository, once
as the main agent and once as a subagent.
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
SID = "readonly-forms-0001"
PUSH_DENY = "BLOCKED: agent git push - agents are not authorized to push"
REWRITE = "BLOCKED: agent git push - force/delete/ref-rewrite push is forbidden."

AGENTS = {"main": {}, "subagent": {"agent_id": "agent-1", "agent_type": "general-purpose"}}

READ_ONLY = [
    "git push --help",
    "git merge --help",
    "git push --dry-run origin HEAD",
    "git push -n origin HEAD",
    "git commit --dry-run",
    "git rebase --show-current-patch",
    "git am --show-current-patch",
    # beyond the audit's list
    "git --help push",
    "git help push",
    "git merge -h",
    "git push -h",
    "git commit --help",
    "git rebase --help",
    "git push --dry-run --force origin HEAD",   # still a dry run
    "git push -nf origin HEAD",
    "git push origin HEAD --dry-run",
    "git push --dry origin HEAD",               # an abbreviation git takes
    "git am --show-current-patch=diff",
    "git commit --dry-run -m x",
    "git commit --dry-run -a",
    "git push --dry-run origin HEAD | cat",
]

STILL_REFUSED = [
    "git commit -n -m x",                        # -n is --no-verify
    "git commit -nm x",
    "git push --help; git push origin master",   # judged per invocation
    "git push --dry-run origin HEAD && git push origin HEAD",
    "git commit --dry-run && git commit -m x",
    "git -c browser.x.cmd=sh push --help",       # help runs a configured program
    "git -c man.viewer=x push --help",
    "git -c core.sshCommand=x push --dry-run origin HEAD",
    "git --config-env=help.browser=X push --help",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=man.viewer GIT_CONFIG_VALUE_0=x git push --help",
    "GIT_CONFIG_PARAMETERS=\"'man.viewer'='x'\" git push --help",
    "export GIT_CONFIG_PARAMETERS=x; git push --help",
    "GIT_CONFIG_PARAMETERS=x; git push --help",
    "PAGER=sh git push --help",
    "env PAGER=sh git push --help",
    "bash -c 'git push --help'",
    "git() { /usr/bin/git push origin master; }; git push --help",
    "git -C /tmp push --dry-run origin HEAD",
    "git push -- --dry-run",                     # an operand, not an option
    "git push -o --dry-run origin HEAD",         # the value of -o
    "git push -on origin HEAD",
    "git push --push-option --dry-run origin HEAD",
    "git push --dry-run --no-dry-run origin HEAD",
    "git push -n --no-d origin HEAD",
    "git push --dry-run --receive-pack=sh .",    # names a program to run
    "git push --dry-run --exec sh .",
    "git push --dry-run 'ext::sh -c x'",
    "git commit -m --dry-run",                   # the message
    "git commit -m x -- --dry-run",              # a pathspec
    "git commit --dry-run --no-dry-run -m x",
    "git commit -am --dry-run",
    "git rebase --show-current-patch -x x",
    "git rebase -i --show-current-patch",
    "git am --show-current-patch extra",
    "git push --hel",
    "git filter-repo -h",                        # an external may read -h otherwise
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
        subprocess.run(["git", "init", "-q", "-b", "master", str(self.repo)], check=True,
                       capture_output=True, env=self.env)

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


@pytest.mark.parametrize("who", sorted(AGENTS))
@pytest.mark.parametrize("command", READ_ONLY)
def test_a_read_only_form_passes(box, command, who):
    proc = box.run(command, **AGENTS[who])
    assert proc.returncode == 0, (command, who, proc.stderr)


@pytest.mark.parametrize("who", sorted(AGENTS))
@pytest.mark.parametrize("command", STILL_REFUSED)
def test_a_form_that_is_not_read_only_is_still_refused(box, command, who):
    proc = box.run(command, **AGENTS[who])
    assert proc.returncode == 2, (command, who, proc.stderr)
    assert "BLOCKED" in proc.stderr, (command, who, proc.stderr)


@pytest.mark.parametrize("who", sorted(AGENTS))
def test_a_dry_run_beside_a_forced_push_does_not_hide_it(box, who):
    box.grant_push()
    proc = box.run("git push --dry-run origin HEAD; git push --force origin feat", **AGENTS[who])
    assert proc.returncode == 2 and REWRITE in proc.stderr, proc.stderr


@pytest.mark.parametrize("who", sorted(AGENTS))
def test_a_forced_dry_run_is_not_read_as_a_rewrite_under_a_grant(box, who):
    grant = box.grant_push()
    proc = box.run("git push --dry-run --force origin HEAD", **AGENTS[who])
    assert proc.returncode == 0, proc.stderr
    assert grant.exists(), "a read-only form spends no grant"


def test_the_push_refusal_still_names_the_push(box):
    proc = box.run("git push --help; git push origin master")
    assert PUSH_DENY in proc.stderr, proc.stderr
