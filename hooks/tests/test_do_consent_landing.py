"""/do consent: one reader for every hook (R4), and what it no longer lands (E2).

hooks/prompt-workflow.py, the flag's one writer, writes it on a `/do ...` UserPromptSubmit into
the hook state dir (CLAUDE_STATE_DIR points at the test's own directory). Every hook decides
through hooks/lib/allowlist.py has_do_consent: the orchestrator gate and the branch firewall
honour it for the main agent; the git-privilege guard releases its merge, plumbing, hard-reset and
ref-mutation rules under it and adds none: a command it allows without /do it allows with it.
git commit, git push and a git command it cannot classify are judged as without /do, and what a
released rule refuses stays refused when it can move the protected branch (the branch
refs/remotes/origin/HEAD names) or the guard cannot tell its landing branch; its blocks name the
commands that land them. No hook honours it for a subagent. A valid /allow or /push grant
authorizes what it authorized before.

Hooks run as subprocesses with PreToolUse payloads shaped as the CLI sends them, in a product
repository whose origin is a local bare repository.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
WRITER = HOOKS / "prompt-workflow.py"
GATE = HOOKS / "pretool-orchestrator-gate.py"
FIREWALL = HOOKS / "pretool-block-branch-pr-worktree.py"
GUARD = HOOKS / "pretool-git-privilege-guard.py"
SID = "do-consent-session-0001"
IDENTITY = ("-c", "user.name=sandbox", "-c", "user.email=sandbox@example.invalid")


class Product:
    """A product repository on master with a feature branch; origin is a local bare clone."""

    def __init__(self, tmp_path: Path):
        self.state = tmp_path / "state"
        self.state.mkdir()
        self.repo = tmp_path / "toyproj"
        self.repo.mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith("CLAUDE") or k == "CLAUDE_PYTHON_BIN"}
        self.env.update(CLAUDE_STATE_DIR=str(self.state), CLAUDE_PROJECT_DIR=str(self.repo),
                        HOME=str(tmp_path / "home"), PYTHONDONTWRITEBYTECODE="1",
                        GIT_CEILING_DIRECTORIES=str(tmp_path))
        (tmp_path / "home").mkdir()
        self.git("init", "-q", "-b", "master")
        (self.repo / "README.md").write_text("# toy\n")
        self.git("add", "README.md")
        self.git(*IDENTITY, "commit", "-qm", "init")
        origin = tmp_path / "toyproj-origin.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(self.repo), str(origin)],
                       check=True, capture_output=True, env=self.env)
        self.git("remote", "add", "origin", str(origin))
        self.git("fetch", "-q", "origin")
        self.git("remote", "set-head", "origin", "master")
        self.git("branch", "feat")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True, env=self.env).stdout.strip()

    def flag(self) -> Path:
        return self.state / f"claude-orchestrator-consent-{SID}.flag"

    def prompt(self, text: str) -> None:
        """The UserPromptSubmit hook that writes (on /do) and clears (otherwise) the flag."""
        payload = {"session_id": SID, "prompt": text, "cwd": str(self.repo),
                   "hook_event_name": "UserPromptSubmit", "transcript_path": ""}
        subprocess.run([sys.executable, str(WRITER)], input=json.dumps(payload), text=True,
                       capture_output=True, cwd=str(self.repo), env=self.env, check=True)

    def hook(self, hook: Path, tool: str, tool_input: dict, subagent: bool = False,
             **env: str) -> subprocess.CompletedProcess:
        payload = {"session_id": SID, "tool_name": tool, "tool_input": tool_input,
                   "cwd": str(self.repo), "hook_event_name": "PreToolUse",
                   "transcript_path": "", "permission_mode": "default"}
        if subagent:
            payload.update(agent_id="agent-0001", agent_type="general-purpose")
        return subprocess.run([sys.executable, str(hook)], input=json.dumps(payload), text=True,
                              capture_output=True, cwd=str(self.repo), env={**self.env, **env})

    def bash(self, hook: Path, command: str, subagent: bool = False, **env: str):
        return self.hook(hook, "Bash", {"command": command}, subagent, **env)


@pytest.fixture
def product(tmp_path):
    p = Product(tmp_path)
    p.prompt("/do push the branch")
    assert p.flag().read_text().strip() == "true"
    return p


def _blocked_naming(proc, *routes: str) -> None:
    """Exit 2, and the /do line names the routes in this order."""
    assert proc.returncode == 2, proc.stderr
    line = next(ln for ln in proc.stderr.splitlines() if ln.startswith("/do consent does not cover"))
    positions = [line.index(r) for r in routes]
    assert positions == sorted(positions), line


def test_gate_and_firewall_honour_do_for_the_main_agent_only(product):
    edit = {"file_path": str(product.repo / "README.md"), "old_string": "toy", "new_string": "t"}
    assert product.hook(GATE, "Edit", edit).returncode == 0
    assert product.hook(GATE, "Edit", edit).returncode == 0  # a second Edit in the turn
    assert product.bash(FIREWALL, "git checkout -b feature/x").returncode == 0
    assert product.bash(FIREWALL, "git checkout -b feature/x", subagent=True).returncode == 2
    product.prompt("next turn")  # D5: /do consent lasts one turn
    assert not product.flag().exists()
    assert product.hook(GATE, "Edit", edit).returncode == 0
    assert product.hook(GATE, "Edit", edit).returncode == 2
    assert product.bash(FIREWALL, "git checkout -b feature/x").returncode == 2


def test_guard_honours_do_for_an_operation_it_still_covers(product):
    assert product.bash(GUARD, "git reset --hard HEAD").returncode == 0
    assert product.bash(GUARD, "git update-ref refs/heads/scratch HEAD").returncode == 0
    # On the protected branch, operations that leave its ref where it is.
    for command in ("git reset --hard", "git reset -- README.md", "git reset README.md",
                    "git cherry-pick -n feat", "git branch -f other master",
                    "git branch -c master backup", "git branch --list master",
                    "git checkout -B other",
                    "git update-ref --no-deref HEAD feat", "git rebase master feat",
                    "git fetch origin '+refs/heads/*:refs/remotes/origin/*'"):
        assert product.bash(GUARD, command).returncode == 0, command
    product.git("checkout", "-q", "feat")
    assert product.bash(GUARD, "git merge master").returncode == 0  # not the protected branch
    for command in ("git rebase master", "git reset --hard master", "git cherry-pick master",
                    "git pull . master", "git update-ref HEAD master", "git branch -m feat2"):
        assert product.bash(GUARD, command).returncode == 0, command
    assert product.bash(GUARD, "git reset --hard HEAD", subagent=True).returncode == 2
    assert product.bash(GUARD, "git merge master", subagent=True).returncode == 2
    product.prompt("next turn")
    assert product.bash(GUARD, "git reset --hard HEAD").returncode == 2


def test_guard_ignores_do_for_commit_push_and_a_protected_merge(product):
    _blocked_naming(product.bash(GUARD, "git commit -m wip"), "/close", "/commit")
    _blocked_naming(product.bash(GUARD, "git push origin HEAD:refs/heads/sb-ud5"), "/push")
    assert "BLOCKED: agent git push" in product.bash(GUARD, "git push").stderr
    # A git command the guard cannot classify may be a push: refused as without /do.
    _blocked_naming(product.bash(GUARD, "$GIT push origin master"), "/push")
    _blocked_naming(product.bash(GUARD, "$GIT status"), "cannot classify", "/close", "/commit")
    _blocked_naming(product.bash(GUARD, "git merge feat"), "/merge")  # on master
    # A merge the guard cannot place in its own cwd counts as protected.
    product.git("checkout", "-q", "feat")
    for command in ("git -C . merge master", "cd . && git merge master", "env git merge master"):
        _blocked_naming(product.bash(GUARD, command), "/merge")
    product.git("remote", "set-head", "origin", "--delete")
    _blocked_naming(product.bash(GUARD, "git merge master"), "/merge")
    # Without /do the same blocks carry no /do line.
    product.prompt("next turn")
    proc = product.bash(GUARD, "git commit -m wip")
    assert proc.returncode == 2 and "/do consent" not in proc.stderr


def test_guard_refuses_under_do_what_can_move_the_protected_branch(product):
    # On the protected branch: an operation that moves the branch HEAD is on.
    for command in ("git reset --hard feat", "git reset --hard feat --",
                    "git pull . feat", "git rebase feat", "git cherry-pick feat", "git revert HEAD",
                    "git am x.patch", "git update-ref HEAD feat", "git branch -m old"):
        _blocked_naming(product.bash(GUARD, command), "/close", "/commit", "/merge")
    product.git("tag", "master")  # `git symbolic-ref --short HEAD` now prints heads/master
    _blocked_naming(product.bash(GUARD, "git merge feat"), "/merge")
    product.git("checkout", "-q", "feat")
    # From another branch: a ref write naming it.
    for command in ("git update-ref refs/heads/master feat", "git update-ref -d refs/heads/master",
                    "git update-ref -m 'a b' refs/heads/master feat", "git update-ref --stdin",
                    "git branch -f master feat", "git branch -f 'master' feat",
                    "git branch -M feat master", "git branch -D master",
                    "git pull origin feat:master", "git rebase feat master",
                    "git filter-branch -- --all"):
        _blocked_naming(product.bash(GUARD, command), "/merge")
    # An operation whose landing branch the guard cannot tell from its own cwd and HEAD.
    for command in ("git checkout -q master && git merge feat", "git switch master; git merge feat",
                    "git merge master; git checkout master", 'bash -c "cd . && git merge master"',
                    "pushd . && git rebase master", "export GIT_DIR=.git; git merge master",
                    ". ./env.sh && git merge master", "timeout 60 git rebase master",
                    "git symbolic-ref HEAD refs/heads/master && git reset --soft feat",
                    "git branch -f $B feat"):
        _blocked_naming(product.bash(GUARD, command), "/merge")
    product.git("checkout", "-q", "--detach")
    _blocked_naming(product.bash(GUARD, "git rebase master"), "/merge")
    # A subagent, and the main agent without /do, are judged as before, with no /do line.
    product.git("checkout", "-q", "feat")
    proc = product.bash(GUARD, "git branch -f master feat", subagent=True)
    assert proc.returncode == 2 and "/do consent" not in proc.stderr
    product.prompt("next turn")
    proc = product.bash(GUARD, "git branch -f master feat")
    assert proc.returncode == 2 and "/do consent" not in proc.stderr


# E2: /do releases rules and never adds one, in each repository state the guard reads.
STATES = ("feature", "feature-unset", "protected", "protected-unset", "detached")
# No rule refuses these without /do, so none refuses them with it: the reviewer's examples
# (PR #16, finding (c)) first, then moves that only the /do rule refused.
ALLOWED_WITHOUT_DO = (
    "git reset --soft HEAD~1", "cd sub && git status", "cd sub && git log",
    "cd sub && git reset --soft HEAD~1", "pushd sub && git diff", "git -C sub status",
    "export GIT_DIR=.git; git log", "timeout 60 git log", "git reset HEAD~1",
    "git reset --soft feat", "git fetch . feat:master", "git checkout -B master feat",
    "git switch --force-create=master feat", "git branch -C feat master",
    "git worktree add -B master ../wt feat", "git symbolic-ref refs/heads/master refs/heads/feat")
REFUSED_WITHOUT_DO = (
    "git reset --hard HEAD~1", "git merge feat", "git merge master", "cd sub && git merge master",
    "git branch -f master feat", "git update-ref refs/heads/scratch HEAD", "git commit -m wip",
    "git push origin HEAD", "$GIT status")


def _in_state(product, state):
    """master and feat one commit past init (HEAD~1 resolves on both), a `sub` directory,
    then: feat or master checked out, or a detached HEAD; `-unset`: no origin/HEAD."""
    (product.repo / "sub").mkdir()
    (product.repo / "sub" / "note.txt").write_text("n\n")
    product.git("add", "sub/note.txt")
    product.git(*IDENTITY, "commit", "-qm", "second")
    product.git("branch", "-f", "feat", "master")
    if state.startswith("feature"):
        product.git("checkout", "-q", "feat")
    elif state == "detached":
        product.git("checkout", "-q", "--detach")
    if state.endswith("-unset"):
        product.git("remote", "set-head", "origin", "--delete")
    return product


def _exits(product, commands):
    """{command: (exit without /do, exit with /do)} for the main agent; /do holds after."""
    with_do = {c: product.bash(GUARD, c).returncode for c in commands}
    product.prompt("next turn")
    assert not product.flag().exists()
    without = {c: product.bash(GUARD, c).returncode for c in commands}
    product.prompt("/do push the branch")
    return {c: (without[c], with_do[c]) for c in commands}


@pytest.mark.parametrize("state", STATES)
def test_do_consent_adds_no_refusal(product, state):
    exits = _exits(_in_state(product, state), ALLOWED_WITHOUT_DO + REFUSED_WITHOUT_DO)
    assert {c: exits[c] for c in ALLOWED_WITHOUT_DO} == {c: (0, 0) for c in ALLOWED_WITHOUT_DO}
    assert {c: exits[c][0] for c in REFUSED_WITHOUT_DO} == {c: 2 for c in REFUSED_WITHOUT_DO}


def test_do_consent_still_refuses_commit_push_and_a_protected_move(product):
    _in_state(product, "feature")
    _blocked_naming(product.bash(GUARD, "git commit -m wip"), "/close", "/commit")
    proc = product.bash(GUARD, "git push origin feat")
    _blocked_naming(proc, "/push")
    assert "BLOCKED: agent git push" in proc.stderr
    assert product.bash(GUARD, "git reset --hard HEAD~1").returncode == 0  # not the protected branch
    # A merge after a cd: the guard cannot tell the branch it lands on.
    _blocked_naming(product.bash(GUARD, "cd sub && git merge master"), "/merge")
    product.git("checkout", "-q", "master")
    _blocked_naming(product.bash(GUARD, "git commit -m wip"), "/close", "/commit")
    _blocked_naming(product.bash(GUARD, "git push origin master"), "/push")
    _blocked_naming(product.bash(GUARD, "git merge feat"), "/merge")
    _blocked_naming(product.bash(GUARD, "git reset --hard HEAD~1"), "/merge")


def test_a_grant_gives_the_same_exit_with_and_without_do(product):
    _in_state(product, "protected")
    now = int(time.time())
    grants = product.state / "claude-grants"
    grants.mkdir()
    head = product.git("rev-parse", "HEAD")
    push_grant = product.state / f"claude-push-grant-{SID}-0001.json"
    push = "git push origin master"
    for prompt in ("/do push the branch", "next turn"):
        product.prompt(prompt)
        assert product.flag().exists() == prompt.startswith("/do")
        for target, command in (("commit", "git commit -m wip"), ("merge", "git merge feat"),
                                ("reset", "git reset --hard HEAD~1")):
            (grants / f"{SID}.json").write_text(json.dumps({
                "task_id": SID, "session_id": SID, "created_at": now, "expires_at": now + 300,
                "allowed_operations": [{"op": "git", "target": target}]}))
            assert product.bash(GUARD, command).returncode == 0, (prompt, command)
        (grants / f"{SID}.json").unlink()
        push_grant.write_text(json.dumps({"branch": "master", "expected_head": head,
                                          "remote": "origin"}))
        assert product.bash(GUARD, push, CLAUDE_PUSH_COMMAND_ACTIVE="1").returncode == 0, prompt
        assert not push_grant.exists()  # spent
        assert product.bash(GUARD, push, CLAUDE_PUSH_COMMAND_ACTIVE="1").returncode == 2, prompt


def test_valid_grants_are_unchanged_under_do(product):
    now = int(time.time())
    grants = product.state / "claude-grants"
    grants.mkdir()
    (grants / f"{SID}.json").write_text(json.dumps({
        "task_id": SID, "session_id": SID, "created_at": now, "expires_at": now + 300,
        "allowed_operations": [{"op": "git", "target": "commit"}]}))
    assert product.bash(GUARD, "git commit -m wip").returncode == 0
    (grants / f"{SID}.json").write_text(json.dumps({
        "task_id": SID, "session_id": SID, "created_at": now, "expires_at": now + 300,
        "allowed_operations": [{"op": "git", "target": "branch"}]}))
    assert product.bash(GUARD, "git branch -f master feat").returncode == 0
    (grants / f"{SID}.json").unlink()
    head = product.git("rev-parse", "HEAD")
    grant = product.state / f"claude-push-grant-{SID}-0001.json"
    grant.write_text(json.dumps({"branch": "master", "expected_head": head, "remote": "origin"}))
    command = "git push origin master"
    assert product.bash(GUARD, command, CLAUDE_PUSH_COMMAND_ACTIVE="1").returncode == 0
    assert not grant.exists()  # spent, as without /do
    _blocked_naming(product.bash(GUARD, command, CLAUDE_PUSH_COMMAND_ACTIVE="1"), "/push")


def test_only_the_reader_the_writer_and_the_clearer_name_the_flag():
    naming = sorted(str(p.relative_to(ROOT)) for p in HOOKS.rglob("*")
                    if p.is_file() and p.suffix in (".py", ".sh", "")
                    and HOOKS / "tests" not in p.parents and "__pycache__" not in p.parts
                    and "orchestrator-consent" in p.read_text(errors="ignore"))
    assert naming == ["hooks/lib/allowlist.py", "hooks/prompt-workflow.py"]
    source = (HOOKS / "prompt-workflow.py").read_text()
    assert source.count("claude-orchestrator-consent-") == 2  # handle_do_consent, _clear_turn_state
    assert '"/tmp"' not in source  # the state dir comes from hooks/lib/harness_state_dir.py alone
