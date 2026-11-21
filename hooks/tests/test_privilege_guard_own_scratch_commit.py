"""An agent's commit in a throwaway repository inside its own scratch directory needs no grant.

The privilege guard refused every agent `git commit` without a /commit grant, also one in a repository the agent had
just made in a work directory of its own (a dev subagent's integration repository, 2026-11-20). Now a commit passes
when the repository it writes to lies wholly inside the caller's own scratch directory: its work tree, git directory,
common directory, object store and index, by real path, as git finds them from the directory the commit runs in. "Own"
is the write policy's one definition (hooks/pretool-tool-policy.py `_scratch_status` == "owner"): a subagent's
<project>/.claude/scratch/<session>/<role>/<agent>/, the main agent's session scratch directory.

Every other commit is refused as before, and the refusal names the caller's own scratch directory. Refused alike: a
linked work tree of the project placed there, a variable or option that points git elsewhere, a link to the project,
a cd that leaves the directory, another agent's directory, and a repository the same call makes (git init and commit
in one call: the guard cannot see where that commit lands before it runs).

The real hook runs as a subprocess; the repositories are throwaway ones under pytest's tmp_path, built by test code.
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
SID = "6a7b8c9d-0e1f-4a2b-9c3d-4e5f6a7b8c9d"
AGENT, OTHER_AGENT = "a0b1c2d3e4f50617", "a8888888888888888"
ID = ("-c", "user.name=sandbox", "-c", "user.email=sandbox@example.invalid")
REFUSED = "BLOCKED: agent git commit"


def _git(cwd, *args, env=None):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, env=env)


def _repo(path, env, commit=True):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main", env=env)
    (path / "a.txt").write_text("a\n")
    _git(path, "add", "a.txt", env=env)
    if commit:
        _git(path, *ID, "commit", "-qm", "base", env=env)


class Box:
    """A project with a repository, the caller's own scratch directory and another agent's, with the shapes below."""

    def __init__(self, base: Path):
        self.base, self.root = base, base / "proj"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_", "PYTHON"))}
        self.env.update(HOME=str(base / "home"), CLAUDE_CONFIG_DIR=str(base / "home" / ".claude"),
                        CLAUDE_STATE_DIR=str(base / "state"), CLAUDE_PROJECT_DIR=str(self.root),
                        TMPDIR=str(base / "tmp"), PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_NOSYSTEM="1")
        for d in ("home/.claude", "state", "tmp"):
            (base / d).mkdir(parents=True)
        scratch = self.root / ".claude" / "scratch" / SID / "dev"
        self.own, self.other = scratch / AGENT, scratch / OTHER_AGENT
        self.session = base / "tmp" / SID                       # the main agent's own: the session's directory
        _repo(self.root, self.env)
        for repo in (self.own / "repo", self.other / "repo", self.session / "repo"):
            _repo(repo, self.env)
        (self.session / ".owner").write_text(json.dumps({"sid": SID}))
        _git(self.root, "worktree", "add", "-q", str(self.own / "wt"), env=self.env)   # the project's, placed there
        os.symlink(self.root, self.own / "link")                                       # a link to the project
        (self.own / "viagit").mkdir()
        os.symlink(self.root / ".git", self.own / "viagit" / ".git")                   # its .git: the project's
        _repo(self.own / "cw", self.env)
        _git(self.own / "cw", "config", "core.worktree", str(self.root), env=self.env)  # work tree: the project

    def run(self, command, cwd=None, main=False, **env):
        payload = {"session_id": SID, "tool_name": "Bash", "tool_input": {"command": self.fill(command)},
                   "cwd": str(cwd or self.root), "hook_event_name": "PreToolUse", "transcript_path": ""}
        if not main:
            payload.update(agent_id=AGENT, agent_type="dev", subagent_type="dev")
        return subprocess.run([sys.executable, "-B", str(GUARD)], input=json.dumps(payload), text=True,
                              capture_output=True, cwd=str(cwd or self.root), env={**self.env, **env}, timeout=120)

    def fill(self, text):
        return text.format(own=self.own, other=self.other, root=self.root, session=self.session)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return Box(tmp_path_factory.mktemp("own-scratch-commit"))


ALLOWED = [
    ("git commit -qm base", "{own}/repo"),
    ("cd {own}/repo && git add -A >/dev/null 2>&1 && git commit -qm base", None),
    ("git -C {own}/repo -c user.name=t -c user.email=t@example.invalid commit -qm base", None),
    ("cd {own} && cd repo && git status && git commit -qm base", None),
]


@pytest.mark.parametrize("command,cwd", ALLOWED)
def test_a_commit_in_a_repository_inside_the_callers_own_scratch_directory_passes(box, command, cwd):
    proc = box.run(command, cwd=box.fill(cwd) if cwd else None)
    assert proc.returncode == 0 and proc.stderr == "", proc.stderr


def test_the_main_agents_own_is_its_session_scratch_directory(box):
    proc = box.run("git -C {session}/repo commit -qm base", main=True)
    assert proc.returncode == 0 and proc.stderr == "", proc.stderr
    proc = box.run("git -C {own}/repo commit -qm base", main=True)   # a subagent's directory is not the main agent's
    assert proc.returncode == 2 and REFUSED in proc.stderr, proc.stderr


REFUSED_CASES = [
    ("git commit -qm x", None),                                              # the project
    ("git commit -qm x", "{own}/wt"),                                        # a linked work tree of the project
    ("GIT_DIR={root}/.git git commit -qm x", "{own}/repo"),                  # a variable: another git directory
    ("GIT_WORK_TREE={root} git commit -qm x", "{own}/repo"),                 # another work tree
    ("GIT_OBJECT_DIRECTORY={root}/.git/objects git commit -qm x", "{own}/repo"),  # another object store
    ("export GIT_DIR={root}/.git; git commit -qm x", "{own}/repo"),
    ("env GIT_INDEX_FILE={root}/.git/index git commit -qm x", "{own}/repo"),
    ("git --git-dir={root}/.git commit -qm x", "{own}/repo"),                # an option: another git directory
    ("git --work-tree={root} commit -qm x", "{own}/repo"),
    ("git -c core.worktree={root} commit -qm x", "{own}/repo"),
    ("git commit -qm x", "{own}/cw"),                                        # its configured work tree: the project
    ("cd {own}/link && git commit -qm x", None),                             # a link to the project
    ("git commit -qm x", "{own}/link"),
    ("git commit -qm x", "{own}/viagit"),                                    # a .git that links to the project's
    ("cd {own}/repo && cd {root} && git commit -qm x", None),                # a cd that leaves the directory
    ("cd {own}/repo; cd {root}; git commit -qm x", None),
    ("cd {own}/repo/../../../../../../.. && git commit -qm x", None),
    ("cd {root} && git -C {own}/repo commit -qm x && git commit -qm y", None),
    ("pushd {root} && git commit -qm x", "{own}/repo"),
    ("cd $D && git commit -qm x", "{own}/repo"),                             # a directory the guard cannot know
    ("(cd {root} && git commit -qm x)", "{own}/repo"),
    ("git -C {other}/repo commit -qm x", None),                              # another agent's scratch directory
    ("git commit -qm x", "{other}/repo"),
    ("git status > .git/config && git commit -qm x", "{own}/repo"),          # a write first
    ("mkdir {own}/new && cd {own}/new && git init -q && git commit -qm base", None),  # made by the same call
    ("bash -c 'git commit -qm x'", "{own}/repo"),
]


@pytest.mark.parametrize("command,cwd", REFUSED_CASES)
def test_every_other_commit_is_refused_and_the_refusal_names_the_own_directory(box, command, cwd):
    proc = box.run(command, cwd=box.fill(cwd) if cwd else None)
    assert proc.returncode == 2 and REFUSED in proc.stderr, proc.stderr
    assert f"your own scratch directory is {box.own}/" in proc.stderr, proc.stderr
    assert "commits there without a grant" in proc.stderr, proc.stderr


def test_a_variable_in_the_guards_own_environment_points_git_away(box):
    proc = box.run("git commit -qm x", cwd=box.own / "repo", GIT_DIR=str(box.root / ".git"))
    assert proc.returncode == 2 and REFUSED in proc.stderr, proc.stderr


def test_the_refusal_keeps_its_first_line(box):
    proc = box.run("git commit -qm x")
    assert proc.stderr.splitlines()[1].startswith("BLOCKED: agent git commit - only the blessed /merge"), proc.stderr
