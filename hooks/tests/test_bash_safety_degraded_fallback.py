"""The removal policy's degraded fallback (lib/bash_safety_rules.py::removal_policy) on a line ending in an option.

When the execution-boundary analyzer gives no verdict (timeout, memory ceiling, crash) the fallback once refused every
line ending on an option, which refused 143 of the everyday commands below (`git status --short`, `date -u`,
`python3 --version`). A trailing option is now plain unless a command of that line names a shell, an interpreter, an
exec wrapper or a removal program (degraded_trailing_option_is_plain). Every form whose missing operand is the danger,
every removal and every assembly channel stays refused. All hook runs use a throwaway HOME and global git config.
"""
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
HOOK = os.path.join(HOOKS_DIR, "pretool-bash-safety.sh")
sys.path.insert(0, os.path.join(HOOKS_DIR, "lib"))

import bash_safety_rules as R  # noqa: E402

DEGRADED = "removal-policy FAIL-CLOSED"
MODES = {"timeout": {"CLAUDE_HOOK_BOUNDARY_TIMEOUT": "0.001s"}, "memory": {"CLAUDE_HOOK_BOUNDARY_MEM_KB": "4096"}}

# Everyday commands ending on an ordinary option, none naming a removal or an assembly channel.
EVERYDAY_TRAILING_OPTION = [
    "git status --short", "git status -s", "git status -sb", "git log --oneline", "git log --oneline -5",
    "git log -1", "git log --graph --oneline --all", "git log -n 3 --stat", "git diff --stat", "git diff --cached",
    "git diff --name-only", "git diff HEAD~1 --stat", "git show --stat", "git branch -a", "git branch -vv",
    "git branch --show-current", "git remote -v", "git fetch --all", "git fetch origin --prune",
    "git rev-parse --show-toplevel", "git describe --tags", "git tag -l", "git tag --list", "git config --list",
    "git shortlog -sn", "git ls-files -m", "git ls-files --others", "git reflog -5", "git cherry -v",
    "git log --since=yesterday --oneline", "git diff --check", "git count-objects -v", "git fsck --no-progress",
    "git --version", "git log --format=%H -1", "git add -A", "git commit --amend --no-edit", "git pull --rebase",
    "git pull --ff-only", "git log --author=me --oneline", "git diff main...HEAD --stat", "ls -la", "ls -l",
    "ls -a", "ls -lh", "ls -1", "ls -R", "ls -lt", "ls src -la", "ls --color=auto", "ls -ltr", "pwd -P", "id -u",
    "hostname -f", "uname -a", "uname -r", "uname -m", "date -u", "date -I", "date --iso-8601=seconds", "date -R",
    "uptime -p", "free -h", "free -m", "df -h", "du -h --max-depth=1", "nproc --all", "top -bn1", "ps -ef",
    "stty -a", "ulimit -a", "wc -l", "grep -n foo file -r", "grep foo file.txt -i", "grep -w foo -R", "rg --files",
    "rg foo --hidden", "rg --type-list", "find . -empty", "find . -size +1M", "find . -mtime -1",
    "find . -name foo -ls", "tree -a", "tree src -d", "uniq -c", "jq -c", "python3 --version", "python3 -V",
    "python --version", "python3 -m pytest -q", "python3 -m pytest -x", "python3 -m pytest tests -v",
    "python3 -m pip --version", "pip --version", "pytest -q", "pytest -x", "pytest -v", "pytest --co -q",
    "ruff check src --fix", "ruff format --check", "cargo --version", "cargo build --release", "cargo fmt --check",
    "rustc --version", "java -version", "javac -version", "mvn -v", "make -j4", "make -n", "cmake --version",
    "gcc --version", "clang --version", "docker ps -a", "docker compose up -d", "docker stats --no-stream",
    "kubectl get pods -A", "kubectl version --client", "terraform fmt -check", "aws --version", "gcloud --version",
    "gh --version", "ss -tlnp", "netstat -tlnp", "set -e", "set -x", "set +x", "hash -r", "ls --help",
    "git --help", "bc -l", "psql -l", "mysql --version", "ssh -V", "ssh-add -l", "gpg --list-keys", "base64 -d",
    "git status --short && git diff --stat", "git log --oneline | head -5", "cd src && ls -la",
    "git diff | head -50", "history | tail -20", "git log -p -1", "sort file.txt | uniq -c | sort -rn",
]

# Forms the degraded fallback must keep refusing: removals, assembly channels, and the structurally incomplete forms
# whose missing operand is the danger, each also behind a wrapper, an assignment, a path, quoting or another command.
STILL_REFUSED = [
    "rm -rf build", "rm build -rf", "rm -rf", "/bin/rm x -f", "unlink -x", "rmdir d -p", "shred x -u",
    "git clean -fdx", "git clean -n", "git -C . clean -f", "git rm -r --cached x -f", "rsync -a src/ dst/ --delete",
    "find . -name x -exec", "find . -name x -delete", "find . -name x -execdir", "find . -name x -ok",
    "truncate f -s", "dd if=a of=b -x", "xargs -0", "ls | xargs -r", "sudo -s", "sudo ls -l", "doas -s",
    "bash -c", "sh -c", "zsh -c", "dash -c", "bash -lc", "bash -s", "sh -", "/bin/bash -c", "\"bash\" -c",
    "b\\ash -c", "ba''sh -c", "FOO=1 bash -c", "nice -n 5 bash -c", "timeout 5 sh -c", "command -p sh -c",
    "exec -a x sh -c", "docker run img sh -c", "ls -la; bash -c", "bash -c; ls -la", "git status && bash -c",
    "env -S", "env --split-string", "env -i", "env FOO=1 -S", "python3 -c", "python3 -", "python3 -m code -i x -c",
    "perl -e", "ruby -e", "awk -f", "sed -i", "eval --", "eval echo -n", "source -x", ". -x", "npx -c",
    "echo >", "echo hi |", "ls &&", "ls ;", "cat <", "x=rm; $x -r", "$(echo rm) -rf", "`echo rm` -rf",
    "$X -r", "${X} -r", "r${E}m -rf", "eval \"$X\" -n", "ls -la \\", "cat <<EOF -n", "ls {a,b} -l",
    "ls * -l", "bash -c 'echo' -x", "grep foo 'unterminated -n",
]


def run_hook(command, **env_extra):
    home = tempfile.mkdtemp(prefix="degraded-home-")
    gitconfig = os.path.join(home, "gitconfig")
    open(gitconfig, "w").close()
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=home, GIT_CONFIG_GLOBAL=gitconfig, **env_extra)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    p = subprocess.run(["bash", HOOK], input=payload, capture_output=True, text=True, cwd=home, env=env)
    return p.returncode, p.stderr


@pytest.mark.parametrize("mode", sorted(MODES))
def test_everyday_trailing_options_pass_the_degraded_fallback(mode):
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda c: (c, *run_hook(c, **MODES[mode])), EVERYDAY_TRAILING_OPTION))
    refused = [(c, err.splitlines()[:1]) for c, code, err in results if code != 0]
    assert not refused, "%d of %d refused under %s: %r" % (len(refused), len(results), mode, refused[:10])


@pytest.mark.parametrize("mode", sorted(MODES))
@pytest.mark.parametrize("command", STILL_REFUSED)
def test_dangerous_neighbours_stay_refused_in_degraded_mode(mode, command):
    code, err = run_hook(command, **MODES[mode])
    assert code == 2, "%s allowed %r" % (mode, command)
    assert err.strip()


def test_the_lifted_corpus_is_exactly_what_question_3_refused():
    """Every corpus line ends on an option, so the old rule refused each one; only the new predicate admits it."""
    for command in EVERYDAY_TRAILING_OPTION:
        assert R.DEGRADED_TRAILING_OPTION.search(command), command
        assert R.degraded_trailing_option_is_plain(command), command


@pytest.mark.parametrize("line", [
    "bash -c", "env -S", "nice bash -c", "xargs -0", "python3 -c", "git clean -f", "find . -exec", "sudo -i",
    "ls -la; sh -s", "grep 'x -n", "ls -l >", "rm -f",
])
def test_predicate_refuses_sensitive_lines(line):
    assert not R.degraded_trailing_option_is_plain(line)


@pytest.mark.parametrize("line", [
    "bash --version", "python3 -V", "python3 -m pytest -q", "git status --short", "ls -la | grep x -i",
    "FOO=1 make -n", "make 2>&1 -j4",
])
def test_predicate_admits_plain_lines(line):
    assert R.degraded_trailing_option_is_plain(line)


def test_analyzer_timeout_default_leaves_headroom_under_load():
    """15 s: the analyzer peaked at 3.4 s with 25 concurrent runs beside 25 CPU-bound processes on 4 cores, and at
    6.0 s (18 of 486 past 5 s) at 50 concurrent runs; the old 5 s default sent those calls to the fallback."""
    assert R.duration("", "15s") == 15.0
    src = open(os.path.join(HOOKS_DIR, "lib", "bash_safety_rules.py"), encoding="utf-8").read()
    assert 'duration(os.environ.get("CLAUDE_HOOK_BOUNDARY_TIMEOUT", ""), "15s")' in src
