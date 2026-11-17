"""The git classifier reads search patterns, piped text and data here-documents as text (OB-L24).

Four readings, each with the inputs that must still be refused:

  - text owners: rg (without `--pre`/`--pre-glob`, or a config file it is
    pointed at), `git grep` (without `-O`) and `git log --grep`, with no
    `-c`/`--config-env` before the subcommand, leave their quoted arguments
    unexecuted, as grep does. ag and ack are not text owners: their `--pager`
    runs a shell;
  - stdin consumers: head, tail, wc, sort, uniq, cut, tr, less, column and nl
    read what a pipe feeds them as text, so a pipe into one keeps a grep
    pattern text. They are not text owners: their own arguments are read
    (`sort --compress-program`);
  - a here-document read only by cat, tee or another data reader, or
    redirected to a file, is data: it runs only the substitutions its
    expansion performs. Fed to bash, sh, ssh, `python3 -`, `source
    /dev/stdin`, a group or a process substitution, or captured by a
    substitution whose output may run, it stays code; a substitution is
    data when its command is text-only and keeps its input as data
    (`git commit -m "$(cat <<'EOF' ...)"`);
  - a program option's value is a command line of its own (`rg --pre`,
    `ag --pager`, `sort --compress-program`), and what echo or printf print
    into a pipe a shell reads is shell text (`echo "git push" | sh`).

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
BULK = HOOKS / "pretool-bulk-commit-detector.py"
sys.path.insert(0, str(HOOKS))

from lib.git_command_classifier import classify_git_command  # noqa: E402

NL = "\n"


def heredoc(head, body, delim="EOF", quote="'"):
    return f"{head} <<{quote}{delim}{quote}{NL}{body}{NL}{delim}"


MUST_PASS = [
    "rg -n 'git reset --hard|git push --force' .",
    "grep -rn 'git push origin\\|git merge origin' . | head -5",
    'rg -n "git rebase -i" docs',
    "grep -rn 'git revert HEAD~1' docs/",
    heredoc("cat > /tmp/notes.md", "notes" + NL + "git push origin master"),
    "git log --oneline -3  # newest first; git push is not needed",
    "git grep -n 'a; git push' -- docs",
    "git log --grep='x; git push' --oneline",
    heredoc("cat", "git push origin master"),
    "rg -n 'a|git push' . | wc -l",
    "grep -n 'x; git push' f | sort | uniq -c | tail -3",
    heredoc("tee /tmp/a.md > /dev/null", "git reset --hard origin/master"),
    "cat <<'EOF' | sort | nl" + NL + "git push origin master" + NL + "EOF",
]

# A commit's message is text; the guard still refuses an agent's commit without
# a /commit grant, so these are checked against the classifier alone.
COMMIT_MESSAGES = [
    heredoc("git commit -F -", "docs: say that git push is not needed"),
    'git commit -m "$(cat <<\'EOF\'' + NL + "docs: the push note" + NL
    + "git push origin master is the owner's" + NL + "EOF" + NL + ')"',
]

MUST_REFUSE = [
    'bash -c "x; git push"',
    'echo "git push" | sh',
    "echo -n 'git push origin master' | sh",
    "printf 'git push origin master\\n' | bash",
    heredoc("bash", "git push origin master"),
    "cat <<'EOF' | bash" + NL + "git push origin master" + NL + "EOF",
    heredoc("ssh host", "git push origin master"),
    heredoc("python3 -", "git push origin master"),
    heredoc("source /dev/stdin", "git push origin master"),
    "{ cat <<'EOF'; } | bash" + NL + "git push origin master" + NL + "EOF",
    "cat <<'EOF' | tee >(sh)" + NL + "git push origin master" + NL + "EOF",
    "cat <<'EOF' |" + NL + "git push origin master" + NL + "EOF" + NL + "bash",
    'eval "$(cat <<\'EOF\'' + NL + "git push origin master" + NL + "EOF" + NL + ')"',
    heredoc("cat > /tmp/x", "$(git push origin master)", quote=""),
    "ag --pager 'true; git push origin master' foo",
    "ack --pager 'true; git push origin master' foo",
    "rg --pre 'git push' x",
    "rg --pre='git push' x",
    "rg --pre-glob '*.md' 'a; git push' x",
    "RIPGREP_CONFIG_PATH=/tmp/c rg 'a; git push' x",
    "grep x f | sort --compress-program='sh -c \"git push\"'",
    "git grep -O'x; git push' foo",
    "git -c core.pager='x; git push' log --grep='a'",
    "grep 'x; git push' f | sh",
    'echo "$(cat <<\'EOF\'' + NL + "git push origin master" + NL + "EOF" + NL + ')" | sh',
    'X="$(cat <<\'EOF\'' + NL + "git push origin master" + NL + "EOF" + NL + ')"; $X',
    '"$(cat <<\'EOF\'' + NL + "git push origin master" + NL + "EOF" + NL + ')"',
    'git commit -m "$(cat <<EOF' + NL + "$(git push origin master)" + NL + "EOF" + NL + ')"',
]


def pushes(command):
    invocations, residuals = classify_git_command(command)
    return [inv.subcommand for inv in invocations if inv.subcommand in ("push", "reset")], residuals


@pytest.mark.parametrize("command", MUST_PASS + COMMIT_MESSAGES)
def test_text_is_not_read_as_a_git_invocation(command):
    found, residuals = pushes(command)
    assert found == [] and residuals == [], (found, residuals)


@pytest.mark.parametrize("command", MUST_REFUSE)
def test_code_is_still_read_as_a_git_invocation(command):
    found, residuals = pushes(command)
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


def _run(hook, command, repo, env, subagent):
    payload = {"session_id": "text-owner-0001", "tool_name": "Bash",
               "tool_input": {"command": command}, "cwd": str(repo),
               "hook_event_name": "PreToolUse", "transcript_path": "",
               "permission_mode": "default"}
    if subagent:
        payload.update(agent_id="agent-text-owner", agent_type="general-purpose")
    return subprocess.run([sys.executable, "-B", str(hook)], input=json.dumps(payload),
                          text=True, capture_output=True, cwd=str(repo), env=env, timeout=120)


@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_the_hooks_let_text_through(tmp_path, subagent):
    repo, env = _sandbox(tmp_path)
    for command in MUST_PASS:
        for hook in (GUARD, BULK):
            proc = _run(hook, command, repo, env, subagent)
            assert proc.returncode == 0, (hook.name, command, proc.stderr)


@pytest.mark.parametrize("subagent", [False, True], ids=["main", "subagent"])
def test_the_guard_still_refuses_code(tmp_path, subagent):
    repo, env = _sandbox(tmp_path)
    for command in MUST_REFUSE:
        proc = _run(GUARD, command, repo, env, subagent)
        assert proc.returncode == 2, (command, proc.stdout, proc.stderr)
        assert "BLOCKED" in proc.stderr, (command, proc.stderr)
