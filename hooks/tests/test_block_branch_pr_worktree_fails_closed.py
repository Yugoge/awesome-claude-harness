"""The branch / PR / worktree hook fails closed.

hooks/pretool-block-branch-pr-worktree.py used to exit 0 on any error it did not
expect and on a payload it could not read, so a crash inside it let a branch, PR
or worktree creation through; an import that failed at module load exited 1,
which the harness treats as a non-blocking hook error. The hook now refuses (exit
2, naming itself, the error and the bypasses) a Bash call that may create one,
unless a bypass is confirmed, and still exits 0 for a call that cannot create one
by its own reading (_may_create) and for another tool's call.

The hook runs as a subprocess with a scratch HOME and CLAUDE_STATE_DIR under the
test's temp dir. The broken cases run a copy of the hook and hooks/lib in which
the classifier, a bypass library or the hook's payload reader raises.
"""

from __future__ import annotations

import importlib.util
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
HOOK = HOOKS / "pretool-block-branch-pr-worktree.py"
CLASSIFIER = Path("lib") / "git_command_classifier.py"
ALLOWLIST = Path("lib") / "allowlist.py"
CORPUS = HOOKS / "tests" / "fixtures" / "adversarial_corpus.json"
SID = "fails-closed-session-0001"
READER_CALL = "data = json.loads(_read_stdin())"

# Ways the hook can break: (file the text is appended to, text appended).
BREAKAGES = {
    # Module load: an import the hook needs fails.
    "classifier-raises-at-import": (CLASSIFIER, "\nraise RuntimeError('simulated classifier failure')\n"),
    "classifier-lacks-a-name": (CLASSIFIER, "\ndel _git_subcommand\n"),
    "allowlist-raises-at-import": (ALLOWLIST, "\nraise RuntimeError('simulated allowlist failure')\n"),
    # Call time: the classifier raises inside main.
    "classifier-raises-when-called": (CLASSIFIER, (
        "\ndef iter_shell_texts(command_text):\n"
        "    raise RuntimeError('simulated classifier failure')\n")),
    # Call time: the payload reader raises inside main (replaced in the hook copy).
    "reader-raises": (None, None),
}
ERROR_NAMES = {
    "classifier-raises-at-import": "RuntimeError",
    "classifier-lacks-a-name": "ImportError",
    "allowlist-raises-at-import": "RuntimeError",
    "classifier-raises-when-called": "RuntimeError",
    "reader-raises": "RuntimeError",
}

CREATING = [
    "git checkout -b feature/x",
    "git switch -c feature/x",
    "git branch new-feature",
    "git worktree add ../wt HEAD",
    "gh pr create --fill",
    "/usr/bin/git -C /some/repo branch newbr",
    "sh -c 'git switch -c inner'",
    "true && git checkout -b chained",
]
UNRELATED = [
    "ls -la",
    "echo hello world",
    "python3 -m pytest -q tests/test_x.py",
    "cat README.md | wc -l",
    "make test",
]


class Sandbox:
    """A scratch HOME and state dir, a project dir, and the hook run against them."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.state = tmp_path / "state"
        self.project = tmp_path / "toyproj"
        for d in (self.home, self.state, self.project):
            d.mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "GIT_", "PYTHON"))}
        self.env.update(HOME=str(self.home), CLAUDE_STATE_DIR=str(self.state),
                        CLAUDE_PROJECT_DIR=str(self.project), PYTHONDONTWRITEBYTECODE="1")

    def payload(self, command, *, tool="Bash", agent_id=None, tool_input=None):
        data = {"session_id": SID, "tool_name": tool,
                "tool_input": tool_input if tool_input is not None else {"command": command},
                "cwd": str(self.project), "hook_event_name": "PreToolUse",
                "transcript_path": "", "permission_mode": "default"}
        if agent_id:
            data["agent_id"] = agent_id
            data["agent_type"] = "dev"
        return json.dumps(data)

    def run(self, hook: Path, command=None, *, raw=None, env_extra=None, **kw):
        if raw is None:
            raw = self.payload(command, **kw)
        env = dict(self.env, **(env_extra or {}))
        return subprocess.run([sys.executable, "-B", str(hook)], input=raw, text=True,
                              capture_output=True, cwd=str(self.project), env=env, timeout=120)

    def hooks_copy(self, name: str) -> Path:
        """A copy of the hook and hooks/lib, broken as BREAKAGES[name] says."""
        dest = self.tmp / f"hooks-{name}"
        shutil.copytree(HOOKS / "lib", dest / "lib", ignore=shutil.ignore_patterns("__pycache__"))
        hook = dest / HOOK.name
        source = HOOK.read_text()
        target, text = BREAKAGES[name]
        if target is None:  # the payload reader raises
            assert source.count(READER_CALL) == 1
            source = source.replace(READER_CALL, "data = _broken_reader()").replace(
                "\ndef main():",
                "\ndef _broken_reader():\n"
                "    raise RuntimeError('simulated payload reader failure')\n\n\n"
                "def main():", 1)
        else:
            lib_file = dest / target
            lib_file.write_text(lib_file.read_text() + text)
        hook.write_text(source)
        return hook

    def live_overnight(self):
        claude = self.project / ".claude"
        claude.mkdir(exist_ok=True)
        (claude / "overnight-state-overnight-sess.json").write_text(json.dumps(
            {"current_phase": "exploring", "end_time": "2099-01-01T00:00:00Z",
             "session_id": "overnight-sess"}))

    def do_consent(self):
        (self.state / f"claude-orchestrator-consent-{SID}.flag").write_text("true")

    def grant(self):
        """A structured sentinel grant for `git checkout`, through its one writer."""
        code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                "from lib.allowlist import write_sentinel_grant; "
                "print(write_sentinel_grant(sys.argv[2], sys.argv[2], "
                "[{'op': 'git', 'target': 'checkout'}]))")
        out = subprocess.run([sys.executable, "-B", "-c", code, str(HOOKS), SID], check=True,
                             capture_output=True, text=True, env=self.env, cwd=str(self.tmp))
        assert Path(out.stdout.strip()) == self.state / "claude-grants" / f"{SID}.json"


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


def _assert_fail_closed_refusal(proc, error_name):
    assert proc.returncode == 2, (proc.returncode, proc.stderr)
    err = proc.stderr
    assert "BLOCKED: pretool-block-branch-pr-worktree.py" in err, err
    assert "not a policy refusal" in err and error_name in err, err
    for way in ("live /dev-overnight session", "use /do", "/allow the specific command"):
        assert way in err, (way, err)


# (i) A broken hook refuses what may create a branch, PR or worktree ...

@pytest.mark.parametrize("name", sorted(BREAKAGES))
def test_a_broken_hook_refuses_a_creating_command(box, name):
    hook = box.hooks_copy(name)
    for command in CREATING:
        _assert_fail_closed_refusal(box.run(hook, command), ERROR_NAMES[name])


# (ii) ... and lets an unrelated call, and another tool's call, through.

@pytest.mark.parametrize("name", sorted(BREAKAGES))
def test_a_broken_hook_lets_an_unrelated_call_through(box, name):
    hook = box.hooks_copy(name)
    for command in UNRELATED:
        proc = box.run(hook, command)
        assert proc.returncode == 0, (command, proc.returncode, proc.stderr)
        assert proc.stderr == "", proc.stderr
    proc = box.run(hook, tool="Read", tool_input={"file_path": str(box.project / "README.md")})
    assert proc.returncode == 0, proc.stderr


def test_a_subagent_is_told_to_pause(box):
    hook = box.hooks_copy("classifier-raises-when-called")
    proc = box.run(hook, "git worktree add ../wt", agent_id="sub-1")
    _assert_fail_closed_refusal(proc, "RuntimeError")
    assert "You are a subagent: PAUSE" in proc.stderr
    assert "PAUSE" not in box.run(hook, "git worktree add ../wt").stderr


def test_a_bypass_check_that_did_not_load_is_named(box):
    hook = box.hooks_copy("allowlist-raises-at-import")
    proc = box.run(hook, "git checkout -b x")
    _assert_fail_closed_refusal(proc, "RuntimeError")
    assert "has_do_consent did not load" in proc.stderr, proc.stderr


# (iii) The refusal's ways to proceed work while the hook is broken.

@pytest.mark.parametrize("bypass", ["live_overnight", "do_consent", "grant"])
def test_each_bypass_named_in_the_refusal_lifts_it(box, bypass):
    hook = box.hooks_copy("classifier-raises-when-called")
    assert box.run(hook, "git checkout -b feature/x").returncode == 2
    getattr(box, bypass)()
    proc = box.run(hook, "git checkout -b feature/x")
    assert proc.returncode == 0, (bypass, proc.stderr)


def test_do_consent_does_not_lift_it_for_a_subagent(box):
    hook = box.hooks_copy("classifier-raises-when-called")
    box.do_consent()
    assert box.run(hook, "git checkout -b feature/x").returncode == 0
    proc = box.run(hook, "git checkout -b feature/x", agent_id="sub-2")
    _assert_fail_closed_refusal(proc, "RuntimeError")


# (iv) Unreadable input: 0 as before, unless its raw text may create one.

@pytest.mark.parametrize("raw", ["", "not json", "[]", "{", "null", "[" * 100000])
def test_unreadable_input_without_a_creating_word_passes(box, raw):
    proc = box.run(HOOK, raw=raw)
    assert proc.returncode == 0, (raw[:40], proc.stderr)


@pytest.mark.parametrize("raw, error, what", [
    ('{"tool_name": "Bash", "tool_input": {"command": "git checkout -b x',  # cut short
     "JSONDecodeError", "could not read its input"),
    ("not json: git switch -c x", "JSONDecodeError", "could not read its input"),
    ('["git worktree add ../wt"]', "AttributeError", "internal error"),
    ('"gh pr create --fill"', "AttributeError", "internal error"),
])
def test_unreadable_input_with_a_creating_word_is_refused(box, raw, error, what):
    proc = box.run(HOOK, raw=raw)
    _assert_fail_closed_refusal(proc, error)
    assert what in proc.stderr and "no bypass can be read" in proc.stderr, proc.stderr


@pytest.mark.parametrize("tool_input", [
    "git checkout -b x",                 # not an object
    {"command": ["git", "branch", "x"]},  # not a string
])
def test_a_payload_of_the_wrong_shape_is_judged_on_its_text(box, tool_input):
    proc = box.run(HOOK, tool_input=tool_input)
    _assert_fail_closed_refusal(proc, "AttributeError")
    # The whole payload is the text judged then, so this one carries no path.
    raw = json.dumps({"tool_name": "Bash", "tool_input": {"command": ["ls", "-la"]}})
    proc = box.run(HOOK, raw=raw)
    assert proc.returncode == 0, proc.stderr


# (v) Normal operation is unchanged.

def test_the_intact_hook_judges_as_before(box):
    for command in CREATING:
        proc = box.run(HOOK, command)
        assert proc.returncode == 2 and "creation is forbidden outside /dev-overnight" in proc.stderr
        assert "not a policy refusal" not in proc.stderr
    for command in UNRELATED + ["git status", "echo git checkout -b x"]:
        assert box.run(HOOK, command).returncode == 0, command


# (vi) The cheap test never clears what the hook's own reading would refuse.

def _blocked_cases():
    tests = _module(HOOKS / "tests" / "test_block_branch_pr_worktree.py", "bbpw_cases")
    cases = []
    for name in dir(tests):
        for mark in getattr(getattr(tests, name), "pytestmark", []):
            if mark.name == "parametrize":
                cases += [v for v in mark.args[1] if isinstance(v, str)]
    return cases


INSERTS = ['""', "''", "\\", "\\\n", '"', "'", "$''", "$X", " ", "'zz'", '"zz"', "#x\n",
           "\\#x\n", "\\ \n", " \n", "\t", ";", "'a b'", '"q\\"r"', "# c\n"]
WRAPS = ["sh -c '{}'", 'bash -c "{}"', "$({})", "`{}`", "env A=1 {}", "true; {}",
         "bash -c 'sh -c \"{}\"'", 'zsh -lc "{}"', "cat <(  {} )", "bash <<EOF\n{}\nEOF",
         "sudo {}", "x=1 {}"]


def _mutant(rnd, command):
    for _ in range(rnd.randint(1, 5)):
        r = rnd.random()
        if r < 0.6:
            i = rnd.randint(0, len(command))
            command = command[:i] + rnd.choice(INSERTS) + command[i:]
        elif r < 0.75:
            i = rnd.randrange(len(command))
            command = command[:i] + command[i].swapcase() + command[i + 1:]
        else:
            command = rnd.choice(WRAPS).format(command)
    return command


def test_what_the_cheap_test_clears_the_hook_never_refuses():
    hook = _module(HOOK, "bbpw_fails_closed")
    blocked = [c for c in _blocked_cases() if hook._detect(c)]
    assert len(blocked) >= 70
    rnd = random.Random(933)
    mutants = [m for m in (_mutant(rnd, rnd.choice(blocked)) for _ in range(6000))
               if hook._detect(m)]
    assert len(mutants) >= 2000
    corpus = [case["payload"] for case in json.loads(CORPUS.read_text())]
    for command in blocked + mutants + [c for c in corpus if hook._detect(c)]:
        assert hook._may_create(command), command
    # Forms the hook reads as git although they delete more than quote characters.
    for command in ("gi'a b't branch new-feature", "g\\ \nit branch -c old new",
                    "g\\#x\nit stash branch fo", "g'x'h pr create", "gi\\\nt checkout -b x"):
        assert hook._detect(command) and hook._may_create(command), command
    for command in UNRELATED + ["", "grep -n foo bar", "echo 'big apple'", "sed -n 1,5p x"]:
        assert not hook._may_create(command), command


def test_the_cheap_test_is_linear():
    hook = _module(HOOK, "bbpw_fails_closed_linear")
    started = time.monotonic()
    for text in ("g'a'" * 40000 + "i", "g" + "'" * 100000 + "i", "gi" + '"' * 100000,
                 "g#\n" * 50000 + "i", "x" * 200000):
        assert hook._may_create(text) is False
    assert hook._may_create("g'a'" * 40000 + "h") is True
    assert time.monotonic() - started < 20
