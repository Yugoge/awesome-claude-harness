"""T4: a Monitor's shell command meets every Bash rule of the PreToolUse launcher.

On CLI 2.1.325 (measured) a Monitor call reaches matcher-less hooks as tool_name "Monitor" with
its shell command in tool_input.command ({description, timeout_ms, command}; a WebSocket Monitor
carries tool_input.ws instead), and reaches hooks under a settings.json "Bash" matcher as a Bash
call {command, description} with the same tool_use_id. The launcher (hooks/pretool-launch.py) is
matcher-less and its Bash rules select by tool_name, so before this change they skipped Monitor:
`gh pr create` was refused as Bash and passed as Monitor. hooks/pretool-monitor-command.py now
hands them the Bash call the CLI hands the Bash matcher, and refuses a Monitor whose command it
cannot read.

Each case runs the registered launcher as a subprocess with a PreToolUse payload as the CLI sends
it; HOME, the state dir, the project and TMPDIR are inside the test's tmp_path.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "hooks" / "pretool-launch.py"
RULE = ROOT / "hooks" / "pretool-monitor-command.py"


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
        record = {"type": "user", "message": {"role": "user", "content": "watch the CI run"},
                  "sessionId": self.sid, "version": "2.1.325"}
        self.transcript.write_text(json.dumps(record) + "\n")

    def env(self) -> dict:
        return {"PATH": os.environ["PATH"], "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
                "CLAUDE_STATE_DIR": str(self.state), "TMPDIR": str(self.tmp / "tmp"),
                "CLAUDE_PROJECT_DIR": str(self.project), "GIT_CEILING_DIRECTORIES": str(self.tmp),
                "PYTHONDONTWRITEBYTECODE": "1"}

    def run(self, tool: str, tool_input) -> subprocess.CompletedProcess:
        body = {"session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(self.project),
                "hook_event_name": "PreToolUse", "permission_mode": "default", "effort": "medium",
                "prompt_id": str(uuid.uuid4()), "tool_name": tool, "tool_input": tool_input,
                "tool_use_id": f"toolu_{uuid.uuid4().hex[:20]}"}
        return subprocess.run([sys.executable, str(LAUNCHER)], input=json.dumps(body), capture_output=True,
                              text=True, env=self.env(), cwd=self.project, timeout=600)


def monitor(command, **extra) -> dict:
    return {"description": "watch", "timeout_ms": 300000, "command": command, **extra}


@pytest.fixture
def session(tmp_path):
    return Session(tmp_path)


def test_gh_pr_create_is_refused_as_bash_and_as_monitor(session):
    bash = session.run("Bash", {"command": "gh pr create --title t --body b", "description": "open PR"})
    assert bash.returncode == 2, bash.stderr
    mon = session.run("Monitor", monitor("gh pr create --title t --body b"))
    assert mon.returncode == 2, (mon.stdout, mon.stderr)
    assert "checked as a Bash call" in mon.stderr


def test_a_branch_created_inside_a_monitor_pipeline_is_refused(session):
    mon = session.run("Monitor", monitor("tail -f build.log & git checkout -b side; wait"))
    assert mon.returncode == 2, (mon.stdout, mon.stderr)


def test_a_write_under_the_projects_claude_hooks_is_refused_as_monitor(session):
    target = session.project / ".claude" / "hooks" / "x.sh"
    bash = session.run("Bash", {"command": f"echo hi > {target}", "description": "w"})
    assert bash.returncode == 2, bash.stderr
    mon = session.run("Monitor", monitor(f"echo hi > {target}; sleep 1"))
    assert mon.returncode == 2, (mon.stdout, mon.stderr)


def test_tailing_a_log_still_passes(session):
    log = session.project / "build.log"
    log.write_text("start\n")
    mon = session.run("Monitor", monitor(f"tail -n +1 -f {log} | grep --line-buffered -E 'PASS|FAIL'"))
    assert mon.returncode == 0, (mon.stdout, mon.stderr)


def test_a_websocket_monitor_runs_no_shell_and_passes(session):
    mon = session.run("Monitor", {"description": "ws", "timeout_ms": 30000, "ws": {"url": "wss://example.invalid/x"}})
    assert mon.returncode == 0, (mon.stdout, mon.stderr)


@pytest.mark.parametrize("tool_input", [
    {"description": "d", "timeout_ms": 1000},                       # neither command nor ws
    {"description": "d", "timeout_ms": 1000, "command": 42},        # not a string
    {"description": "d", "timeout_ms": 1000, "command": "   "},     # empty
    {"description": "d", "timeout_ms": 1000, "command": ["gh", "pr", "create"]},
    "gh pr create",                                                 # tool_input not an object
], ids=["missing", "number", "blank", "list", "not-an-object"])
def test_a_monitor_whose_command_cannot_be_read_is_refused(session, tool_input):
    mon = session.run("Monitor", tool_input)
    assert mon.returncode == 2, (mon.stdout, mon.stderr)
    assert "cannot be read" in mon.stderr


def _rule_module():
    spec = importlib.util.spec_from_file_location("_monitor_command", RULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_launcher_rule_a_bash_call_reaches_is_run_on_monitor():
    mod = _rule_module()
    launcher = importlib.util.spec_from_file_location("_launch", LAUNCHER)
    lmod = importlib.util.module_from_spec(launcher)
    launcher.loader.exec_module(lmod)
    # a Bash call reaches it and a Monitor call does not (by its tools), or it is registered on every
    # tool and picks its Bash rules by tool_name inside (the write gate)
    derived = [(r.name, r.path, r.tools, r.timeout) for r in lmod.RULES
               if (r.tools is not None and "Bash" in r.tools and "Monitor" not in r.tools) or r.name == "write-gate"]
    assert [(r.name, r.path, r.tools, r.timeout) for r in mod.BASH_RULES] == derived
    assert [r[0] for r in derived] == ["write-gate", "wrapper-userintent", "grep-backtrack-guard", "attribution-pre",
                                       "block-branch-pr-worktree", "bulk-commit-detector", "git-privilege-guard"]
    # the other every-tool rules: the orchestrator gate decides Monitor itself (the Bash cap); the
    # rest do not branch on Bash, or (the no-background rule) leave Monitor out on purpose
    every_tool = [r.name for r in lmod.RULES if r.tools is None]
    assert every_tool == ["orchestrator-gate", "block-background-tasks", "do-block-subagents", "read-size-guard",
                          "workflow-gate", "write-gate"]
    own = [r for r in lmod.RULES if r.path == "pretool-monitor-command.py"]
    assert len(own) == 1 and own[0].tools == ("Monitor",)
    # its timeout covers the Bash rules it runs one after another, so an overrun of this rule
    # (a non-blocking error, the call goes on) can only follow an inner rule's own timeout
    assert own[0].timeout > sum(r.timeout for r in mod.BASH_RULES)


def test_the_bash_call_is_the_one_the_cli_hands_the_bash_matcher():
    mod = _rule_module()
    data = {"session_id": "s", "tool_use_id": "toolu_x", "tool_name": "Monitor",
            "tool_input": {"description": "p1", "timeout_ms": 20000, "command": "echo mon1; sleep 1"}}
    out = json.loads(mod.as_bash(data, "echo mon1; sleep 1"))
    assert out["tool_name"] == "Bash" and out["tool_use_id"] == "toolu_x"
    assert out["tool_input"] == {"command": "echo mon1; sleep 1", "description": "p1"}


def test_a_rule_that_cannot_load_the_launcher_library_refuses_a_monitor_command(tmp_path):
    hooks = tmp_path / "hooks"
    (hooks / "lib").mkdir(parents=True)
    (hooks / "lib" / "__init__.py").write_text("")
    copy = hooks / RULE.name
    copy.write_text(RULE.read_text())
    body = {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Monitor", "tool_use_id": "toolu_x",
            "tool_input": monitor("tail -f build.log")}
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}
    run = subprocess.run([sys.executable, str(copy)], input=json.dumps(body), capture_output=True, text=True,
                         env=env, cwd=tmp_path, timeout=60)
    assert run.returncode == 2, (run.stdout, run.stderr)
    assert "did not load" in run.stderr
