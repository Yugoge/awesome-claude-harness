#!/usr/bin/env python3
"""The /stop user-intent guard decides on a parsed EXECUTION of the harness home's wrapper (OB-L38).

hooks/pretool-wrapper-userintent.py refuses a Bash call that runs the harness home's
hooks/stop.sh or scripts/break-overnight-lock.py without a live /stop user-intent sentinel,
and consumes that single-use sentinel only on such a run. A command that merely mentions
either name (a grep, a syntax check, a lookup, a project's own script of the same name) is
not a run: it passes and leaves the sentinel in place. Where the run's target cannot be
read (a computed command word, a file the same command creates, an unparseable command)
and the command mentions the wrapper, the guard stays closed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "pretool-wrapper-userintent.py"
SID = "ob-l38-session"


@pytest.fixture()
def env(tmp_path):
    home = tmp_path / "home"
    harness = home / ".claude"
    (harness / "hooks").mkdir(parents=True)
    (harness / "scripts").mkdir(parents=True)
    (harness / "hooks" / "stop.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    (harness / "scripts" / "break-overnight-lock.py").write_text("print('x')\n")
    for f in ((harness / "hooks" / "stop.sh"), (harness / "scripts" / "break-overnight-lock.py")):
        f.chmod(0o755)
    project = tmp_path / "project"
    for rel in ("docs", "scripts", "hooks"):
        (project / rel).mkdir(parents=True)
    (project / "docs" / "a.md").write_text("bash hooks/stop.sh\n")
    (project / "scripts" / "stop.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    (project / "scripts" / "stop.sh").chmod(0o755)
    (project / "scripts" / "break-overnight-lock.py").write_text("print('own')\n")
    (project / "hooks" / "stop.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    # a symlink to the wrapper that already exists before the command runs
    (project / "alias.sh").symlink_to(harness / "hooks" / "stop.sh")
    state = tmp_path / "state"
    state.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return {"home": home, "harness": harness, "project": project, "state": state,
            "scratch": scratch}


def _run(env, command, cwd=None):
    cwd = str(cwd or env["project"])
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": SID,
               "cwd": cwd}
    run_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    run_env.update(HOME=str(env["home"]), CLAUDE_HOME=str(env["harness"]),
                   CLAUDE_STATE_DIR=str(env["state"]),
                   CLAUDE_USERINTENT_SENTINEL_DIR=str(env["state"]))
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, cwd=cwd, env=run_env, timeout=60)


def _sentinel(env):
    return env["state"] / f"claude-stop-userintent-{SID}.flag"


def _fmt(env, command):
    return command.format(H=env["harness"], S=env["scratch"], P=env["project"])


MUST_PASS = [
    'grep -rn "bash hooks/stop.sh" docs/',
    'rg -n "start.sh|stop.sh" scripts/',
    "bash -n hooks/stop.sh",
    "command -v stop.sh",
    "./scripts/stop.sh",
    "bash scripts/stop.sh",
    "python3 ./scripts/break-overnight-lock.py",
    "git log --oneline --grep stop.sh",
    'echo "bash ~/.claude/hooks/stop.sh"',
    "cat ~/.claude/hooks/stop.sh",
    "bash -n ~/.claude/hooks/stop.sh",
    "python3 -m py_compile ~/.claude/scripts/break-overnight-lock.py",
    "ls ~/.claude/hooks | grep stop.sh",
    "git diff -- hooks/stop.sh scripts/break-overnight-lock.py",
    "cat > {S}/notes.md <<'EOF'\nbash ~/.claude/hooks/stop.sh\nEOF",
    'git commit -m "fix stop.sh quoting"',
    "sed -n 1,20p ~/.claude/hooks/stop.sh",
    "shellcheck ~/.claude/hooks/stop.sh",
]


@pytest.mark.parametrize("command", MUST_PASS)
def test_a_mention_passes_without_a_sentinel(env, command):
    proc = _run(env, _fmt(env, command))
    assert proc.returncode == 0, proc.stderr


def test_a_syntax_check_from_the_harness_home_is_not_a_run(env):
    proc = _run(env, "bash -n hooks/stop.sh", cwd=env["harness"])
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("command", MUST_PASS)
def test_a_mention_leaves_a_live_sentinel_in_place(env, command):
    _sentinel(env).write_text("true")
    proc = _run(env, _fmt(env, command))
    assert proc.returncode == 0, proc.stderr
    assert _sentinel(env).exists(), "a mere mention consumed the single-use /stop sentinel"


def test_after_stop_a_mention_then_the_real_run(env):
    _sentinel(env).write_text("true")
    assert _run(env, 'grep -rn "bash hooks/stop.sh" docs/').returncode == 0
    assert _sentinel(env).exists()
    proc = _run(env, 'bash "$HOME/.claude/hooks/stop.sh"')
    assert proc.returncode == 0, proc.stderr
    assert not _sentinel(env).exists(), "the real run must consume the sentinel"
    assert (env["state"] / f"claude-stop-helper-auth-{SID}.json").exists()
    again = _run(env, 'bash "$HOME/.claude/hooks/stop.sh"')
    assert again.returncode == 2, "a consumed sentinel must not authorize a second run"


MUST_REFUSE = [
    "bash ~/.claude/hooks/stop.sh",
    "python3 ~/.claude/scripts/break-overnight-lock.py",
    "cd ~/.claude/hooks && ./stop.sh",
    "ln -s ~/.claude/hooks/stop.sh {S}/s && {S}/s",
    "bash -c 'bash ~/.claude/hooks/stop.sh'",
    "source ~/.claude/hooks/stop.sh",
    ". ~/.claude/hooks/stop.sh",
    "env bash ~/.claude/hooks/stop.sh",
    "env -i A=1 bash ~/.claude/hooks/stop.sh",
    "/usr/bin/env python3 ~/.claude/scripts/break-overnight-lock.py",
    "exec bash ~/.claude/hooks/stop.sh",
    "command bash ~/.claude/hooks/stop.sh",
    "nice -n 5 bash ~/.claude/hooks/stop.sh",
    "timeout -s KILL 5 bash ~/.claude/hooks/stop.sh",
    "setsid nohup bash ~/.claude/hooks/stop.sh",
    'bash "$HOME/.claude/hooks/stop.sh"',
    'bash "${{HOME}}/.claude/hooks/stop.sh"',
    "bash '{H}/hooks/stop.sh'",
    '"$HOME"/.claude/hooks/stop.sh',
    "~/.claude/hooks/stop.sh",
    "{H}/hooks/stop.sh --flag",
    "bash ~/.claude/hooks/st*.sh",
    'bash ~/.claude/hooks/"stop".sh',
    "bash --norc -e -o pipefail -- ~/.claude/hooks/stop.sh",
    "python3 -u -W ignore ~/.claude/scripts/break-overnight-lock.py --x",
    "sh <(cat ~/.claude/hooks/stop.sh)",
    "cat ~/.claude/hooks/stop.sh | bash",
    "python3 - < ~/.claude/scripts/break-overnight-lock.py",
    "bash -s < ~/.claude/hooks/stop.sh",
    "cd ~/.claude/hooks && bash -s < stop.sh",
    "bash < ~/.claude/hooks/stop.sh",
    "source /dev/stdin < ~/.claude/hooks/stop.sh",
    "bash -c 'bash -c \"bash ~/.claude/hooks/stop.sh\"'",
    "bash -c 'cd ~/.claude/hooks; ./stop.sh'",
    "f(){{ bash ~/.claude/hooks/stop.sh; }}; f",
    "X=~/.claude/hooks/stop.sh; bash \"$X\"",
    "X=~/.claude/hooks/stop.sh; \"$X\"",
    "$(echo bash) ~/.claude/hooks/stop.sh",
    "cp ~/.claude/hooks/stop.sh {S}/x.sh && bash {S}/x.sh",
    "cp ~/.claude/hooks/stop.sh {S}/ && bash {S}/stop.sh",
    "cat ~/.claude/hooks/stop.sh > {S}/y; bash {S}/y",
    "PATH=~/.claude/hooks:$PATH stop.sh",
    "echo ~/.claude/hooks/stop.sh | xargs bash",
    "find ~/.claude/hooks -name stop.sh -exec bash {{}} \\;",
    "python3 -c \"import subprocess; subprocess.run(['bash', '{H}/hooks/stop.sh'])\"",
    "bash <<'EOF'\nbash ~/.claude/hooks/stop.sh\nEOF",
    "bash ./alias.sh",
    "./alias.sh",
    "bash ~/.claude/hooks/stop.sh \"",
    "true; bash ~/.claude/hooks/stop.sh # grep",
    "sudo -n bash ~/.claude/hooks/stop.sh",
    "time bash -x ~/.claude/hooks/stop.sh",
    "eval 'bash ~/.claude/hooks/stop.sh'",
    "(cd ~/.claude && bash hooks/stop.sh)",
    "watch -n1 bash ~/.claude/hooks/stop.sh",
    "script -qc 'bash ~/.claude/hooks/stop.sh' /dev/null",
    "perl -e 'system(\"bash ~/.claude/hooks/stop.sh\")'",
    "git -c alias.x='!bash ~/.claude/hooks/stop.sh' x",
    "echo 'bash ~/.claude/hooks/stop.sh' | at now",
    "bash -c 'cp ~/.claude/hooks/stop.sh {S}/q && bash {S}/q'",
]


@pytest.mark.parametrize("command", MUST_REFUSE)
def test_a_run_of_the_wrapper_is_refused_without_a_sentinel(env, command):
    proc = _run(env, _fmt(env, command))
    assert proc.returncode == 2, (proc.returncode, proc.stderr)
    assert "USER-INTENT GUARD" in proc.stderr


def test_the_project_script_of_the_same_name_is_not_the_wrapper(env):
    proc = _run(env, "bash -c './scripts/stop.sh'")
    assert proc.returncode == 0, proc.stderr
