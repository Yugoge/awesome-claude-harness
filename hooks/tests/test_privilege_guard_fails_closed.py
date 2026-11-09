"""The git-privilege guard fails closed, and the classifier's old option name still loads.

P9 renamed the classifier's git value-option set to GIT_GLOBAL_VALUE_OPTS; another
stream's guard and branch hook still import it as `_GIT_GLOBAL_VALUE`. Without the
old name the guard raised at load, Python exited 1, and the harness ran the command
unjudged: the guard failed open. The classifier keeps the old name as the table, and
the guard turns any error it did not expect into exit 2 for a Bash call that may run
git, naming the error. Another tool's call and a command that cannot run git still
exit 0.

The guard runs as a subprocess with a scratch HOME, a scratch CLAUDE_STATE_DIR and a
scratch git repository under the test's temp dir. The broken cases run a copy of the
guard and hooks/lib whose classifier lacks a name or raises.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
GUARD = HOOKS / "pretool-git-privilege-guard.py"
CLASSIFIER = Path("lib") / "git_command_classifier.py"
CORPUS = HOOKS / "tests" / "fixtures" / "adversarial_corpus.json"
SID = "fail-closed-session-0001"
IDENTITY = ("-c", "user.name=sandbox", "-c", "user.email=sandbox@example.invalid")

# The other stream's import forms, verbatim: the guard's commit reads, the branch hook.
OLD_NAME_IMPORTS = (
    "from lib.git_command_classifier import (\n"
    "    _unquote_token,\n"
    "    _segments as _shell_segments,\n"
    "    _command_token_index as _cmd_token_index,\n"
    "    _ENV_ASSIGN_RE as _ENV_ASSIGN_RE,\n"
    "    _GIT_GLOBAL_VALUE as _GIT_GLOBAL_VALUE,\n"
    ")\n"
    "from lib.git_command_classifier import (\n"
    "    _segments, _basename, _WRAPPERS, _ENV_ASSIGN_RE,\n"
    "    _command_token_index, _GIT_GLOBAL_VALUE, _git_subcommand,\n"
    ")\n"
)

# Ways the classifier can break, each appended to a copy of it.
BREAKAGES = {
    # The merge-train case: the guard imports the old name, the classifier lacks it.
    "lacks-old-name": "\nglobals().pop('_GIT_GLOBAL_VALUE', None)\n",
    "lacks-current-name": "\ndel GIT_GLOBAL_VALUE_OPTS\n",
    "raises-at-import": "\nraise RuntimeError('simulated classifier failure')\n",
    "raises-when-called": ("\ndef classify_git_command(command_text):\n"
                           "    raise RuntimeError('simulated classifier failure')\n"),
}


class Sandbox:
    """A scratch HOME, state dir and repository, and the guard run against them."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.state = tmp_path / "state"
        self.repo = tmp_path / "toyproj"
        for d in (self.home, self.state, self.repo):
            d.mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "GIT_", "PYTHON"))}
        self.env.update(HOME=str(self.home), CLAUDE_STATE_DIR=str(self.state),
                        CLAUDE_PROJECT_DIR=str(self.repo), PYTHONDONTWRITEBYTECODE="1",
                        GIT_CEILING_DIRECTORIES=str(tmp_path), GIT_CONFIG_NOSYSTEM="1")
        self.git("init", "-q", "-b", "master")
        (self.repo / "README.md").write_text("# toy\n")
        self.git("add", "README.md")
        self.git(*IDENTITY, "commit", "-qm", "init")
        self.msg = tmp_path / "commit-msg-20990101-000001.txt"
        self.msg.write_text("chore(toy): sandbox change\n")
        self.commit = f'git -C "{self.repo}" commit -F "{self.msg}"'

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True, env=self.env).stdout

    def grant(self) -> Path:
        """A structured sentinel grant for `git commit`, through its one writer."""
        code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                "from lib.allowlist import write_sentinel_grant; "
                "print(write_sentinel_grant(sys.argv[2], sys.argv[2], "
                "[{'op': 'git', 'target': 'commit'}]))")
        out = subprocess.run([sys.executable, "-B", "-c", code, str(HOOKS), SID], check=True,
                             capture_output=True, text=True, env=self.env, cwd=str(self.tmp))
        path = Path(out.stdout.strip())
        assert path == self.state / "claude-grants" / f"{SID}.json", out.stdout
        return path

    def run(self, guard: Path, command: str | None = None, *, tool: str = "Bash",
            tool_input: dict | None = None, raw: str | None = None):
        if raw is None:
            payload = {"session_id": SID, "tool_name": tool,
                       "tool_input": tool_input if tool_input is not None else {"command": command},
                       "cwd": str(self.repo), "hook_event_name": "PreToolUse",
                       "transcript_path": "", "permission_mode": "default"}
            raw = json.dumps(payload)
        return subprocess.run([sys.executable, "-B", str(guard)], input=raw, text=True,
                              capture_output=True, cwd=str(self.repo), env=self.env, timeout=120)

    def hooks_copy(self, name: str, breakage: str = "", old_name_import: bool = False) -> Path:
        """A copy of the guard and hooks/lib, its classifier broken by `breakage`.

        old_name_import adds the other stream's import of `_GIT_GLOBAL_VALUE` to the
        guard, as the merge of the two streams carries it."""
        dest = self.tmp / f"hooks-{name}"
        shutil.copytree(HOOKS / "lib", dest / "lib", ignore=shutil.ignore_patterns("__pycache__"))
        guard = dest / GUARD.name
        source = GUARD.read_text()
        if old_name_import:
            anchor = "\nif __name__ == '__main__':\n    main()"
            assert source.count(anchor) == 1
            source = source.replace(anchor, "\n" + OLD_NAME_IMPORTS + anchor)
        guard.write_text(source)
        classifier = dest / CLASSIFIER
        classifier.write_text(classifier.read_text() + breakage)
        return guard


@pytest.fixture
def box(tmp_path):
    return Sandbox(tmp_path)


def _module(path: Path, name: str):
    if str(HOOKS) not in sys.path:
        sys.path.insert(0, str(HOOKS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# (i) The old name loads, in both import forms, and means the value-option table.

def test_the_old_name_imports_in_both_forms(box):
    code = ("import sys; sys.path.insert(0, sys.argv[1])\n" + OLD_NAME_IMPORTS
            + "from lib.git_command_classifier import GIT_GLOBAL_VALUE_OPTS\n"
            "assert _GIT_GLOBAL_VALUE is GIT_GLOBAL_VALUE_OPTS\n"
            "sys.path.insert(0, sys.argv[1] + '/lib')\n"
            "from git_command_classifier import _GIT_GLOBAL_VALUE as bare\n"
            "print(sorted(bare))\n")
    proc = subprocess.run([sys.executable, "-B", "-c", code, str(HOOKS)], capture_output=True,
                          text=True, env=box.env, cwd=str(box.tmp))
    assert proc.returncode == 0, proc.stderr
    assert "--attr-source" in proc.stdout


def test_the_old_name_answers_which_options_take_the_next_word():
    classifier = _module(HOOKS / CLASSIFIER, "classifier_old_name")
    old = classifier._GIT_GLOBAL_VALUE
    # The set before the split, but --exec-path, whose value git takes only as `=<dir>`.
    for opt in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
                "--config-env", "--attr-source", "--shallow-file"):
        assert opt in old, opt
    assert "--exec-path" not in old
    assert classifier._git_subcommand(["--attr-source", "HEAD", "commit", "-qm", "x"])[0] == "commit"
    assert classifier._git_subcommand(["--exec-path=/x", "commit"])[0] == "commit"


def test_the_merged_guard_loads_and_judges(box):
    guard = box.hooks_copy("merged", old_name_import=True)
    box.grant()
    assert box.run(guard, box.commit).returncode == 0
    assert box.run(guard, "ls -la").returncode == 0
    assert box.run(guard, "git push origin HEAD").returncode == 2


# (ii) A commit naming its repository and message file, under a sentinel grant.

def test_a_granted_commit_is_allowed_and_an_ungranted_one_refused(box):
    proc = box.run(GUARD, box.commit)
    assert proc.returncode == 2 and "BLOCKED: agent git commit" in proc.stderr, proc.stderr
    box.grant()
    proc = box.run(GUARD, box.commit)
    assert proc.returncode == 0, proc.stderr


# (iii) A broken classifier refuses what may run git; (iv) it lets the rest through.

@pytest.mark.parametrize("name", sorted(BREAKAGES))
def test_a_broken_classifier_refuses_a_git_command(box, name):
    guard = box.hooks_copy(name, BREAKAGES[name], old_name_import=(name == "lacks-old-name"))
    box.grant()
    for command in (box.commit, "git status", "$GIT push origin HEAD"):
        proc = box.run(guard, command)
        assert proc.returncode == 2, (command, proc.returncode, proc.stderr)
        assert "internal error, not a policy refusal" in proc.stderr, proc.stderr
        assert ("ImportError" if name.startswith("lacks") else "RuntimeError") in proc.stderr


@pytest.mark.parametrize("name", sorted(BREAKAGES))
def test_a_broken_classifier_lets_a_non_git_call_through(box, name):
    guard = box.hooks_copy(name, BREAKAGES[name], old_name_import=(name == "lacks-old-name"))
    for command in ("ls -la", "echo hello world"):
        proc = box.run(guard, command)
        assert proc.returncode == 0, (command, proc.returncode, proc.stderr)
    proc = box.run(guard, tool="Read", tool_input={"file_path": str(box.repo / ".gitignore")})
    assert proc.returncode == 0, proc.stderr


# Unreadable input: 0 as before, unless its raw text may run git.

def test_unreadable_input_is_refused_only_when_it_may_run_git(box):
    for raw in ("", "not json", "[]"):
        assert box.run(GUARD, raw=raw).returncode == 0, raw
    for raw in ('{"tool_name": "Bash", "tool_input": {"command": "git push origin HEAD',
                '["git push origin HEAD"]'):
        proc = box.run(GUARD, raw=raw)
        assert proc.returncode == 2 and "not a policy refusal" in proc.stderr, (raw, proc.stderr)


# The cheap test never calls git-free what the classifier would judge.

GIT_SHAPED = [
    "git status", "/usr/bin/git push", '"git" push', "'git' push", "g\\it push", 'gi""t push',
    "gi\\\nt push", "GIT push", "$GIT push", "${G}it push", "G=g; ${G}it push",
    "$(which git) push", "`which git` push", "<(echo x) push", 'env -i "$GIT" push',
    'bash -c "cd x; git push"',
]
GIT_FREE = ["ls -la", "make test", "cat README.md", "echo hi | sh", "python3 -m pytest -q"]


def test_what_the_cheap_test_clears_holds_no_git_for_the_classifier():
    guard = _module(GUARD, "privilege_guard_fails_closed")
    classifier = _module(HOOKS / CLASSIFIER, "classifier_fails_closed")
    assert all(guard._may_run_git(c) for c in GIT_SHAPED)
    assert not any(guard._may_run_git(c) for c in GIT_FREE)
    corpus = [case["payload"] for case in json.loads(CORPUS.read_text())]
    for command in GIT_SHAPED + GIT_FREE + corpus:
        if not guard._may_run_git(command):
            assert classifier.classify_git_command(command) == ([], []), command
