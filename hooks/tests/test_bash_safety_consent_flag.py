"""lib/bash_safety_rules.py consent_flag_rule through the real hook: no Bash call forges the /do consent flag.

The flag is <state dir>/claude-orchestrator-consent-<session id>.flag. Its one writer is hooks/prompt-workflow.py
(UserPromptSubmit, when the owner types /do); every hook decides /do consent from it (lib/allowlist.has_do_consent).
A Bash call that writes, creates, moves, links, copies onto or deletes it is refused, by literal path, through the
state-root variable, a variable set in the command, a glob, a relative path after cd, and inside eval, bash -c,
interpreter code (python -c, python on a heredoc, node -e, perl -e) and an unquoted heredoc's substitution. Reading
it stays allowed. The rule runs before the /do and /allow releases, and binds subagents too.

Every call runs pretool-bash-safety.sh with a scratch HOME, state dir and git config and an empty protected-runtime
file. No command is ever executed.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
SAFETY = HOOKS / "pretool-bash-safety.sh"
WRITER = HOOKS / "prompt-workflow.py"
SID = "consent-flag-rule"
sys.path.insert(0, str(HOOKS))
from lib.runtime_guard.config import REQUIRED_KEYS  # noqa: E402

RULE = "do-consent-flag-write"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("consent-flag")
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
    return {"env": env, "repo": str(repo), "state": str(state),
            "flag": str(state / f"claude-orchestrator-consent-{SID}.flag")}


def run(sandbox, command, subagent=False):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": SID,
               "cwd": sandbox["repo"], "hook_event_name": "PreToolUse"}
    if subagent:
        payload.update(agent_id="agent-consent-flag", agent_type="dev")
    return subprocess.run(["bash", str(SAFETY)], input=json.dumps(payload), capture_output=True, text=True,
                          env=sandbox["env"], cwd=sandbox["repo"], timeout=120)


def fill(sandbox, template):
    return template.replace("<F>", sandbox["flag"]).replace("<S>", sandbox["state"])


# The lane's must-refuse forms, then the path forms and channels the rule covers.
MUST_REFUSE = [
    """python3 -c 'open("<F>","w").write("true")'""",
    "echo 1 > <F>",
    "touch <F>",
    "cp /tmp/x <F>",
    """node -e 'require("fs").writeFileSync("<F>","1")'""",
    "python3 - <<'EOF'\nopen(\"<F>\", \"w\").write(\"true\")\nEOF",
    'eval "touch <F>"',
]
ALSO_REFUSED = [
    # interpreters and nested shells
    """perl -e 'open(F, ">", "<F>")'""",
    """python3 -c 'import os; open(os.environ["CLAUDE_STATE_DIR"] + "/claude-orchestrator-" + "con" + "sent-x.flag", "w")'""",
    """echo 'open("<F>", "w").write("true")' | python3""",
    "python3 <<< 'open(\"<F>\", \"w\")'",
    "bash -c 'echo true > <F>'",
    "sh -c 'touch <F>'",
    "sudo tee <F> < /dev/null",
    "cat <<X > /tmp/out\n$(touch <F>)\nX",
    # every write mechanism
    "echo true >> <F>",
    "printf true > <F>",
    "mv /tmp/x <F>",
    "mv <F> /tmp/saved",
    "ln -s /tmp/x <F>",
    "rm -f <F>",
    "unlink <F>",
    "truncate -s0 <F>",
    "dd of=<F> if=/dev/zero",
    "sed -i s/false/true/ <F>",
    "install -m 600 /dev/null <F>",
    "find <S> -name 'claude-orchestrator-consent-*' -delete",
    "rm -rf <S>",
    # through the state-root variable, a variable set here, a glob, a relative path
    'touch "$CLAUDE_STATE_DIR/claude-orchestrator-consent-x.flag"',
    'echo true > "${CLAUDE_STATE_DIR}"/claude-orchestrator-consent-x.flag',
    'echo true > "$CLAUDE_STATE_DIR"/c*',
    'touch "$CLAUDE_STATE_DIR"/claude-orchestrator-consent-?.flag',
    "rm -f <S>/claude-*",
    'F=<F>; touch "$F"',
    'D=<S>; echo true > "$D"/claude-*.flag',
    "cd <S> && echo true > claude-orchestrator-consent-x.flag",
    "cd <S> && touch c*",
    "cp ./claude-* <S>/",
]
MUST_PASS = [
    "cat <F>",
    "ls <S>",
    "python3 -c 'print(1)'",
    "touch /tmp/other-file",
    # reads and writes elsewhere
    "head -1 <F>",
    "test -f <F> && echo yes",
    "grep -rn claude-orchestrator-consent hooks/",
    "find <S> -name 'claude-orchestrator-consent-*'",
    "ls -la <S>/claude-orchestrator-consent-*",
    "echo hello > out.txt",
    "cp a b /tmp/",
    "mv /tmp/x <S>/",
    "touch <S>/notes.txt",
    'echo x > "$OUT"',
    "cat /tmp/x > /tmp/y",
]


@pytest.mark.parametrize("command", MUST_REFUSE + ALSO_REFUSED)
def test_a_bash_write_of_the_consent_flag_is_refused(sandbox, command):
    proc = run(sandbox, fill(sandbox, command))
    assert proc.returncode == 2, (command, proc.stdout, proc.stderr)
    assert RULE in proc.stderr, (command, proc.stderr)


@pytest.mark.parametrize("command", MUST_REFUSE)
def test_a_subagent_is_refused_the_same(sandbox, command):
    proc = run(sandbox, fill(sandbox, command), subagent=True)
    assert proc.returncode == 2 and RULE in proc.stderr, (command, proc.stderr)


@pytest.mark.parametrize("command", MUST_PASS)
def test_a_read_or_an_unrelated_write_passes(sandbox, command):
    proc = run(sandbox, fill(sandbox, command))
    assert proc.returncode == 0, (command, proc.stderr)


def test_do_consent_does_not_release_the_rule(sandbox):
    flag = Path(sandbox["flag"])
    flag.write_text("true")
    try:
        assert run(sandbox, "git status").returncode == 0
        proc = run(sandbox, fill(sandbox, "echo true > <S>/claude-orchestrator-consent-other.flag"))
        assert proc.returncode == 2 and RULE in proc.stderr, proc.stderr
        assert "Neither /do nor /allow releases this rule" in proc.stderr
    finally:
        flag.unlink()


def test_the_one_writer_still_sets_the_flag_outside_bash(sandbox, tmp_path):
    """prompt-workflow.py writes the flag on a typed /do (a UserPromptSubmit hook, not an agent Bash call)."""
    env = dict(sandbox["env"], CLAUDE_PROJECT_DIR=sandbox["repo"])
    payload = {"session_id": SID, "prompt": "/do something", "cwd": sandbox["repo"],
               "hook_event_name": "UserPromptSubmit", "transcript_path": ""}
    flag = Path(sandbox["flag"])
    try:
        subprocess.run([sys.executable, str(WRITER)], input=json.dumps(payload), text=True, capture_output=True,
                       cwd=sandbox["repo"], env=env, check=True, timeout=120)
        assert flag.read_text().strip() == "true"
        assert run(sandbox, fill(sandbox, "cat <F>")).returncode == 0
    finally:
        if flag.exists():
            flag.unlink()
