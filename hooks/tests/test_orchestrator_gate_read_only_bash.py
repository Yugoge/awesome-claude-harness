"""OB-L03: a Bash command proven read-only does not use one of the orchestrator's 5 Bash slots.

hooks/pretool-orchestrator-gate.py counted every main-agent Bash call toward its cap of 5, so a turn
of plain inspection (`git status --short`, `git log --oneline -5`, `rg -n def src`, `ls src`,
`wc -l f`, `git show --stat HEAD`) was refused at its sixth call. The owner decided that a command
hooks/lib/bash_read_only proves read-only, read from the shell_parse tree, passes uncounted. A
command that can run code of its choosing, write a file or redirect output still counts: an
interpreter, an option that writes or runs a program (git --output/--ext-diff/--textconv/-c,
rg --pre, find -delete/-exec/-fprint, sort -o, sed w/-i, awk system()/print >), any substitution,
process substitution, redirection or assignment prefix, a pager, xargs, env.

Gate cases run the gate (and, for the registered pipeline, hooks/pretool-launch.py) as a subprocess
with the PreToolUse payload the CLI sends; HOME, state dir, project and TMPDIR live in tmp_path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "hooks" / "pretool-orchestrator-gate.py"
LAUNCH = ROOT / "hooks" / "pretool-launch.py"
REFUSED = "Bash used consecutively beyond limit"

sys.path.insert(0, str(ROOT / "hooks" / "lib"))
try:
    from bash_read_only import is_read_only  # noqa: E402
except ImportError:  # the base commit has no such module: every unit case fails there
    def is_read_only(_command):
        raise AssertionError("hooks/lib/bash_read_only.py is missing")
finally:
    sys.path.pop(0)

MUST_PASS = ["git status --short", "git log --oneline -5", "rg -n def src", "ls src", "wc -l f",
             "git show --stat HEAD"]

MORE_READ_ONLY = [
    "git diff HEAD~1 -- a.py", "git branch -a", "git branch --show-current", "git tag -l 'v*'", "git remote -v",
    "git config --get user.name", "git -C sub status", "git --no-pager log -3", "git stash list",
    "git rev-parse HEAD", "git ls-files | wc -l", "git log --no-ext-diff -p -1", "git grep -n foo",
    "find . -name '*.py'", "find . -newer x -type f", "grep -rn foo src | head -20", "ls src/*.py",
    "cat a b | wc -l", "sed -n '10,20p' f", "sed 's/a/b/g' f", "awk '{print $1}' f", "sort f | uniq -c",
    "ls missing 2>/dev/null", "rg foo 2>&1 | head", "cd src && ls", "test -f x && cat x", "echo hi",
    "rg --files | rg test", "git worktree list", "! git diff --quiet", "uniq -c -i", "sort f | uniq -f1 -s2 --count",
]

# AUDIT.md section 2 OB-L03 and the lane's list, then adversarial variants.
MUST_REFUSE = [
    "python3 x.py", "git log --output=/tmp/x", "rg --pre sh x", "find . -delete", "sort -o f x",
    "git -c core.pager=sh log", "ls $(pwd)", "ls > out",
]

ADVERSARIAL = [
    # git: options that write or run, global options, aliases, non-listing forms
    "git log --outp=/tmp/x", "git --exec-path=/x log", "git diff --ext-diff", "git diff --ext",
    "git show --textconv HEAD:a", "git cat-file --filters HEAD:a", "git diff-tree --ext-diff HEAD",
    "git -p log", "git --git-dir=/x log", "git --help", "git help log", "git st", "git grep -O foo",
    "git grep -nOless foo", "git branch new", "git branch -D x", "git branch -m a b", "git branch -l new",
    "git branch --set-upstream-to=o/m", "git tag v1", "git config user.name x", "git config --unset a",
    "git stash", "git stash drop", "git worktree add x", "git reflog expire", "git remote add o u", "git -C",
    "git",
    # rg / find / sort / uniq
    "rg --pre=sh x", "rg -z x", "rg --hostname-bin=sh x", "rg foo *", "find . -exec rm {} ;",
    "find . -execdir x ;", "find . -ok x ;", "find . -okdir x ;", "find . -fprint f", "find . -fprint0 f",
    "find . -fprintf f %p", "find . -fls f", "find . -name *.py", "sort -uo f x", "sort --output=f x",
    "sort --compress-program=sh x", "sort *", "uniq a b",
    # sed / awk
    "sed 'w FILE' f", "sed -i s/a/b/ f", "sed --in-place s/a/b/ f", "sed --in s/a/b/ f", "sed '1p;w out' f",
    "sed 's/a/b/w out' f", "sed 's/a/b/e' f", "sed -f s.sed f", "awk 'BEGIN{system(\"id\")}'",
    "awk '{print > \"out\"}' f", "awk '{print | \"sh\"}' f", "awk -f p.awk f",
    "awk 'BEGIN{getline < \"/etc/x\"}'",
    # substitutions, redirections, heredocs, assignments
    "ls `pwd`", "diff <(ls) <(ls a)", "ls >> out", "ls 2>/tmp/x", "ls >&f", "ls 3>/dev/null",
    "ls >/dev/nul", "cat < f", "cat <<EOF\nx\nEOF", "cat <<< x", "echo $HOME", "ls ${x}", "ls {a,$(id)}",
    "git log --since=$(date)", "PAGER=sh git log", "GIT_EXTERNAL_DIFF=sh git diff", "LESSOPEN='|sh' ls",
    "printf -v PATH x",
    # pipes into, wrappers, pagers, shells, compounds, paths, background
    "git log | sh", "ls | xargs rm", "env", "env ls", "less f", "more f", "man ls", "exec ls", "command ls",
    "nice ls", "time python3 x", "eval ls", "bash -c ls", "alias ls=python3; ls", "ls &", "(ls)",
    "{ ls; }", "f(){ ls; }; f", "/bin/ls", "./ls", "ls; python3 x", "cd $HOME", "tee f", "cp a b",
    "rm f", "touch f", "mkdir d",
    # bash's test -v/-R evaluate the operand's subscript arithmetically, running a $(...) in it even when
    # single-quoted; any word still spelling a substitution or expansion after quote removal counts
    "test -v 'a[$(python3 x.py)]'", "[ -v 'a[$(touch /tmp/x)]' ]", "echo ok && test -v 'x[$(python3 x.py)]'",
    "test -v x", "[ -R x ]", "test ! -v 'a[1]'", "test 'a[$(id)]' -eq 1", "[ 'a[`id`]' -lt 2 ]",
    "printf '%d' 'a[$(id)]'", "echo 'a[$(id)]'", "cd 'a[$(id)]'", "wc -l 'a[${x}]'", "grep '$((1))' f",
    "cat 'a[$[1]]'", "ls \"$(id)\"",
    # `--` ends option parsing: GNU uniq then takes dash-named words as INPUT and OUTPUT and creates or
    # truncates the OUTPUT (uniq -- -in -out writes -out)
    "uniq -- -in -out", "uniq -c -- -a -b", "uniq -- -a", "uniq -i --", "sort f | uniq -d -- -x -y",
]

# The other checkers against the same class: an end-of-options `--` before a script word, GNU option
# permutation (an option after an operand still parses), an abbreviated or `=`-joined long option. Each
# runs code or writes a file as GNU tools parse it; each already counts, and they guard the audit.
END_OF_OPTIONS = [
    "sort x -o f", "sort --o=f x", "sort --outp f x", "sed p f -i", "sed --in-pl=.b p f", "sed -n -- 'w out' f",
    "sed -n -- 'p;w out' f", "sed -n --expr='w out' f", "awk -- 'BEGIN{system(\"id\")}'",
    "awk -v x=1 -- '{print > \"o\"}' f", "rg x --pre=sh", "git log --oneline --outp=x", "git diff --textc",
    "find . -name x -fprint f", "printf -vPATH x", "uniq a b -c",
]


@pytest.mark.parametrize("command", MUST_PASS + MORE_READ_ONLY)
def test_read_only_command_is_proven(command):
    assert is_read_only(command) is True


@pytest.mark.parametrize("command", MUST_REFUSE + ADVERSARIAL)
def test_command_that_can_run_or_write_is_not_proven(command):
    assert is_read_only(command) is False


@pytest.mark.parametrize("command", END_OF_OPTIONS)
def test_end_of_options_and_permuted_or_abbreviated_option_is_not_proven(command):
    assert is_read_only(command) is False


@pytest.mark.parametrize("command", [None, "", "   ", 7, "ls 'unterminated", pytest.param("x" * 9000, id="oversize")])
def test_unreadable_command_is_not_proven(command):
    assert is_read_only(command) is False


class Session:
    def __init__(self, tmp_path: Path):
        self.tmp, self.sid = tmp_path, str(uuid.uuid4())
        self.home = tmp_path / "home"
        self.project = tmp_path / "project"
        self.state = tmp_path / "state"
        for d in (self.project / ".claude", self.state, tmp_path / "tmp"):
            d.mkdir(parents=True, exist_ok=True)
        tdir = self.home / ".claude" / "projects" / "-project"
        tdir.mkdir(parents=True)
        self.transcript = tdir / f"{self.sid}.jsonl"
        self.transcript.write_text(json.dumps(
            {"type": "user", "message": {"role": "user", "content": "look around the repo"}}) + "\n")
        self.n = 0

    def run(self, command: str, hook: Path = GATE, **extra) -> subprocess.CompletedProcess:
        self.n += 1
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
               "CLAUDE_HOME": str(ROOT), "CLAUDE_STATE_DIR": str(self.state), "TMPDIR": str(self.tmp / "tmp"),
               "CLAUDE_PROJECT_DIR": str(self.project), "GIT_CEILING_DIRECTORIES": str(self.tmp),
               "PYTHONDONTWRITEBYTECODE": "1"}
        body = {"session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(self.project),
                "hook_event_name": "PreToolUse", "permission_mode": "default", "tool_name": "Bash",
                "tool_use_id": f"toolu_{self.n:04d}", "tool_input": {"command": command, **extra}}
        return subprocess.run([sys.executable, str(hook)], input=json.dumps(body), capture_output=True,
                              text=True, env=env, cwd=self.project, timeout=120)

    def allowed(self, command: str, hook: Path = GATE, **extra) -> bool:
        p = self.run(command, hook, **extra)
        assert p.returncode in (0, 2), (p.returncode, p.stdout, p.stderr)
        refused = p.returncode == 2 or '"deny"' in p.stdout
        if refused:
            assert REFUSED in p.stderr + p.stdout, (p.stdout, p.stderr)
        return not refused

    @property
    def state_file(self) -> Path:
        return self.state / f"claude-tool-streak-{self.sid}.json"


def test_six_plus_read_only_calls_in_a_turn_pass(tmp_path):
    s = Session(tmp_path)
    commands = MUST_PASS + ["git branch -a", "find . -name '*.py'", "sed -n 1,5p f"]
    assert [s.allowed(c) for c in commands] == [True] * len(commands)
    assert not s.state_file.exists(), "a read-only Bash call writes no count"


def test_sixth_python_call_still_refused(tmp_path):
    s = Session(tmp_path)
    assert [s.allowed("python3 x.py") for _ in range(5)] == [True] * 5
    p = s.run("python3 x.py")
    assert p.returncode == 2 and "Bash used consecutively beyond limit (6/5)" in p.stderr, p.stderr


@pytest.mark.parametrize("command", MUST_REFUSE[1:])
def test_must_refuse_command_still_counts(tmp_path, command):
    s = Session(tmp_path)
    assert [s.allowed(command) for _ in range(5)] == [True] * 5
    p = s.run(command)
    assert p.returncode == 2 and "Bash used consecutively beyond limit (6/5)" in p.stderr, p.stderr


def test_read_only_calls_neither_spend_nor_free_a_slot(tmp_path):
    s = Session(tmp_path)
    for _ in range(5):
        assert s.allowed("python3 x.py")
    assert all(s.allowed(c) for c in MUST_PASS), "the cap is spent, read-only calls still pass"
    assert not s.allowed("python3 x.py"), "read-only calls in between do not reset the count"


def test_background_read_only_call_counts(tmp_path):
    s = Session(tmp_path)
    for _ in range(5):
        assert s.allowed("git status --short", run_in_background=True)
    assert not s.allowed("git status --short", run_in_background=True)


@pytest.mark.parametrize("command", ["test -v 'a[$(python3 x.py)]'", "[ -v 'a[$(touch /tmp/x)]' ]",
                                     "echo ok && test -v 'x[$(python3 x.py)]'"])
def test_arithmetic_subscript_code_counts_through_the_launcher(tmp_path, command):
    """test -v 'a[$(cmd)]' runs cmd in bash: through hooks/pretool-launch.py it is counted."""
    s = Session(tmp_path)
    assert [s.allowed(command, hook=LAUNCH) for _ in range(6)] == [True] * 5 + [False]


def test_uniq_end_of_options_counts_through_the_launcher(tmp_path):
    """uniq -- -a -b truncates -b in GNU uniq: through hooks/pretool-launch.py it is counted."""
    s = Session(tmp_path)
    assert [s.allowed("uniq -- -a -b", hook=LAUNCH) for _ in range(6)] == [True] * 5 + [False]


def test_registered_pipeline(tmp_path):
    """Through hooks/pretool-launch.py, the PreToolUse hook settings.json registers for every tool."""
    s = Session(tmp_path)
    assert [s.allowed(c, hook=LAUNCH) for c in MUST_PASS] == [True] * len(MUST_PASS)
    assert [s.allowed("python3 x.py", hook=LAUNCH) for _ in range(6)] == [True] * 5 + [False]
