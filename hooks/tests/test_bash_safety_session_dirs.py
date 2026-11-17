"""session_dirs.txt through the real bash-safety hook, with the permission layer out of the picture.

The name may stand only as a search pattern (grep, rg, git grep, git log -S/-G/--grep) or in a git commit message;
every read, write or run of the file, every mention the rule cannot classify, and every glob or expansion written
to land on the file is refused by pretool-bash-safety.sh alone. Every call runs with a scratch HOME, state dir and
git config, an empty protected-runtime file, and a throwaway repository as its working directory. No command is
ever executed.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
sys.path.insert(0, str(HOOKS))
from lib.runtime_guard.config import REQUIRED_KEYS  # noqa: E402


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("bash-safety-session-dirs")
    home, state, repo, tmp = base / "home", base / "state", base / "repo", base / "tmp"
    for d in (home / ".claude", state, repo, tmp):
        d.mkdir(parents=True)
    (base / "gitconfig").write_text("[user]\n\tname = sandbox\n\temail = sandbox@example.invalid\n")
    runtime = base / "protected-runtime.json"
    runtime.write_text(json.dumps({"schema_version": 1, **{k: [] for k in REQUIRED_KEYS}}))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
           "CLAUDE_STATE_DIR": str(state), "GIT_CONFIG_GLOBAL": str(base / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
           "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
           "CLAUDE_PROTECTED_RUNTIME_FILE": str(runtime)}
    (repo / "README.md").write_text("toy\n")
    for step in (["init", "-q", "-b", "master"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *step], cwd=repo, env=env, check=True, capture_output=True)
    return {"env": env, "repo": str(repo)}


def run(sandbox, command, subagent=False):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "bash-safety-session-dirs",
               "cwd": sandbox["repo"], "hook_event_name": "PreToolUse"}
    if subagent:
        payload.update(agent_id="agent-bash-safety-session-dirs", agent_type="dev")
    return subprocess.run(["bash", str(HOOKS / "pretool-bash-safety.sh")], input=json.dumps(payload),
                          capture_output=True, text=True, env=sandbox["env"], cwd=sandbox["repo"], timeout=120)


# The owner's decision: the name as a search pattern or in a commit message is a mention, not a use.
MENTIONS = [
    "grep -rn session_dirs.txt docs/",
    "git log --oneline -S session_dirs.txt",
    "rg -n 'session_dirs.txt' hooks/",
    "git grep -n session_dirs.txt",
    'git commit -m "docs: explain session_dirs.txt"',
    "grep -e session_dirs.txt -rn docs/",
    'grep -rn "session_dirs.txt" docs/ | head -5',
    "/usr/bin/grep -rn session_dirs.txt docs/",
    "timeout 10 grep -rn session_dirs.txt docs/",
    "bash -c 'grep -rn session_dirs.txt docs/'",
    "find docs -name '*.md' -exec grep -l session_dirs.txt {} +",
    "rg -n --hidden -g '*.md' session_dirs.txt docs",
    "git grep -n -e session_dirs.txt -- docs",
    "git -C /tmp/repo log --oneline -S session_dirs.txt",
    "git log --oneline -Ssession_dirs.txt",
    "git log --grep=session_dirs.txt",
    'git commit -am "docs: explain session_dirs.txt"',
    'git commit --message="session_dirs.txt notes"',
    'git commit -q -m "a" -m "b: session_dirs.txt"',
    'git commit -m "fix the hash and alias notes about session_dirs.txt"',
    "git commit -m \"$(cat <<'EOF'\ndocs: explain session_dirs.txt\n\nbody\nEOF\n)\"",
    "git commit -F - <<'EOF'\ndocs: session_dirs.txt\nEOF",
]

# Commands near the name that never named the file stay allowed: the rule adds no refusal to them.
UNRELATED = [
    "cat *.txt",
    'cat "$SESSION_DIR/foo.txt"',
    "ls session_dirs/",
    "cat docs/session-notes.md",
    'python3 -c "import requests; s = requests.Session()"',
    "git status",
    'BASE_DIR="$(harness_state_dir)/agentic-commit/push/${REPO_HASH}"',
    'echo "$(cd /opt/x; ls sessions)" > out.txt',
]

# Every read, write or run of the file, every mention outside a pattern or message, and every glob or expansion
# written to land on it.
REFUSED = [
    # the lane's must-still-refuse examples
    "cat session_dirs.txt",
    "grep -f session_dirs.txt x",
    "grep x session_dirs.txt",
    "python3 -c \"open('session_dirs.txt','w')\"",
    "bash -c 'cat session_dirs.txt'",
    "find / -name session_dirs.txt -exec cat {} \\;",
    "cat $(echo session_dirs.txt)",
    "cat session_dirs.tx?",
    "echo x > session_dirs.txt",
    "sh session_dirs.txt",
    "source session_dirs.txt",
    'eval "cat session_dirs.txt"',
    "git commit -F session_dirs.txt",
    "rg --pre ./x session_dirs.txt",
    # file operands and positions that flip a pattern into a file
    "grep -e x -- session_dirs.txt",
    "grep session_dirs.txt session_dirs.txt",
    "grep --fil=session_dirs.txt x",
    "grep $opt session_dirs.txt docs",
    "echo docs | xargs grep -rn session_dirs.txt",
    "rg --pre=./x session_dirs.txt",
    "rg --files session_dirs.txt",
    "rg -z session_dirs.txt",
    "rg -nz session_dirs.txt",
    "grep -rn session_dirs.txt docs/ > session_dirs.txt",
    "grep -c session_dirs.txt < session_dirs.txt",
    "grep -rn session_dirs.txt docs/; cat session_dirs.txt",
    'bash -c "grep -e session_dirs.txt x; cat session_dirs.txt"',
    "bash -c $'grep -e session_dirs.txt x'",
    "eval grep -e session_dirs.txt x",
    # a search program that is not the one named
    "./grep session_dirs.txt docs",
    "/grep session_dirs.txt docs",
    "alias grep=cat; grep session_dirs.txt",
    'grep() { cat "$@"; }; grep session_dirs.txt',
    'function grep { cat "$1"; }; grep session_dirs.txt',
    "eval 'gr''ep(){ cat $1; }'; grep session_dirs.txt docs",
    "hash -p ./x grep; grep session_dirs.txt docs",
    "source x.sh; grep session_dirs.txt docs",
    ". x.sh && grep -rn session_dirs.txt docs",
    "PATH=.:$PATH grep session_dirs.txt docs",
    "export PATH=.:$PATH; grep session_dirs.txt docs",
    "env PATH=. grep session_dirs.txt docs",
    "GREP_OPTIONS=-f grep session_dirs.txt docs",
    "RIPGREP_CONFIG_PATH=./c rg session_dirs.txt",
    # git calls that run a program, read the file as a path, or take it outside the message
    "git -c core.pager=less grep session_dirs.txt",
    "git grep -O session_dirs.txt",
    "git grep --textconv session_dirs.txt",
    "git log --ext-diff -S session_dirs.txt",
    "git log -- session_dirs.txt",
    "git add session_dirs.txt",
    "git commit -m x session_dirs.txt",
    "git commit -m x -- session_dirs.txt",
    'git commit -m "x $(cat session_dirs.txt)"',
    'git commit -m "$(cat <<EOF\nx $(cat session_dirs.txt)\nEOF\n)"',
    # globs, expansions and spellings that land on the file
    "grep -rn session_dirs.txt sess*",
    "cat sess*",
    "cat *dirs.txt",
    "cat session_dirs.{txt,bak}",
    'cat "session_dirs.${x}txt"',
    "cat $'session_dirs\\x2etxt'",
    'cat session_dirs.t"x"t',
    "cat session_dirs.t\\\nxt",
    "SESSION_DIRS.TXT=1; cat SESSION_DIRS.TXT",
    # interpreter code
    "python3 -c \"open('session_dirs.' + 'txt').read()\"",
    "python3 -c \"import os; p='session_dirs'; open(p+'.tx'+'t')\"",
    "node -e \"require('fs').readFileSync('session_dirs.txt')\"",
    "python3 - <<'EOF'\nopen('session_dirs.txt').read()\nEOF",
    # anything else that names it
    "for f in session_dirs.txt; do cat $f; done",
    "[[ -f session_dirs.txt ]] && echo y",
    "tee session_dirs.txt < /dev/null",
    "cp /tmp/x session_dirs.txt",
    "sudo cat session_dirs.txt",
    "cat <(echo) session_dirs.txt",
    "ls # session_dirs.txt",
    "echo session_dirs.txt",
    'grep -rn session_dirs.txt docs/ "unterminated',
]


@pytest.mark.parametrize("command", MENTIONS)
def test_a_pattern_or_message_mention_passes(sandbox, command):
    for subagent in (False, True):
        r = run(sandbox, command, subagent)
        assert r.returncode == 0, (command, r.stderr)


@pytest.mark.parametrize("command", UNRELATED)
def test_a_command_that_never_names_the_file_passes(sandbox, command):
    r = run(sandbox, command, subagent=True)
    assert r.returncode == 0, (command, r.stderr)


@pytest.mark.parametrize("command", REFUSED)
def test_a_read_write_or_run_of_the_file_is_refused(sandbox, command):
    for subagent in (False, True):
        r = run(sandbox, command, subagent)
        assert r.returncode == 2, (command, r.stdout, r.stderr)
        assert "session_dirs.txt is never read, written or executed" in r.stderr, (command, r.stderr)
        assert "neither releases it" in r.stderr
