"""T8: pins on hooks/pretool-orchestrator-gate.py that no other test held.

Pins the gate's always-allowed set, its Bash cap and its permanent plan-mode block, where no test did.

Already pinned elsewhere, and not repeated here:
- the ALWAYS_ALLOWED literal, BASH_CAPPED and PERMANENTLY_BLOCKED as parsed from the source, and the
  literal's agreement with CLAUDE.md's "Always allowed" line
  (test_orchestrator_gate_newer_tools.py::test_the_whitelist_is_exactly_the_documented_set);
- five Bash calls pass and the sixth is refused, an Agent dispatch resets the count
  (test_orchestrator_gate_in_flight.py::test_in_flight_keeps_the_rule_and_the_counts, CURRENT_BASH);
- Monitor counts in Bash's count, reset by a dispatch (test_orchestrator_gate_newer_tools.py);
- prompt-workflow.py removes the streak file at each prompt (test_prompt_workflow_turn_state.py);
- EnterPlanMode refused without /do, both wordings (test_orchestrator_gate_in_flight.py).

Pinned here:
1. The set the gate runs with, read from the loaded module (not only its literal), equals CLAUDE.md's
   list, and every documented name passes more than once a turn without a count of its own.
   CLAUDE.md's stated cap ("capped at 5 calls: the 6th") is the gate's BASH_MAX_CONSECUTIVE.
2. The Bash cap end to end through the real prompt hook: the 6th call is refused and the next prompt
   (hooks/prompt-workflow.py) lets Bash run again. No other tool resets the count, whether it is
   always allowed, counted once per turn, or refused.
3. EnterPlanMode and ExitPlanMode: refused on every call, under /do too, and nothing is counted;
   only an /allow grant naming the tool passes, for one call (posttool-allowlist-consume.py spends
   it), and a grant naming one does not pass the other.

Each hook runs as a subprocess, its HOME, state dir, project and TMPDIR inside the test's tmp_path.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
GATE = HOOKS / "pretool-orchestrator-gate.py"
PROMPT_WORKFLOW = HOOKS / "prompt-workflow.py"
CONSUME = HOOKS / "posttool-allowlist-consume.py"
CAPPED = "used consecutively beyond limit"
PERMANENT = "Permanently blocked"
PLAN_TOOLS = ("EnterPlanMode", "ExitPlanMode")

# Input shapes as the CLI sends them; the gate reads only tool_name (and Write's file_path).
TOOL_INPUT = {
    "Agent": {"subagent_type": "general-purpose", "prompt": "x", "run_in_background": False},
    "TodoWrite": {"todos": [{"content": "a", "status": "pending", "activeForm": "a"}]},
    "AskUserQuestion": {"questions": []},
    "Skill": {"skill": "simplify"},
    "CronCreate": {"cron": "7 * * * *", "prompt": "x"},
    "CronDelete": {"id": "c1"},
    "CronList": {},
    "ScheduleWakeup": {"delaySeconds": 600, "prompt": "x"},
    "Bash": {"command": "true", "description": "probe"},
    "Read": {"file_path": "/etc/hostname"},
    "Glob": {"pattern": "*.py"},
    "Grep": {"pattern": "x"},
    "Monitor": {"description": "CI run", "timeout_ms": 300000, "command": "gh run watch 1"},
    "TaskStop": {"task_id": "b1"},
    "ListAgents": {},
    "PushNotification": {"message": "done", "status": "proactive"},
    "Edit": {"file_path": "/nonexistent/a.py", "old_string": "a", "new_string": "b"},
    "WebFetch": {"url": "https://example.invalid", "prompt": "x"},
    "TaskCreate": {"subject": "a", "description": "b"},
    "EnterPlanMode": {},
    "ExitPlanMode": {"plan": "x"},
}


def documented_allowed() -> set:
    """The names on CLAUDE.md's "- Always allowed:" line, up to its first full stop."""
    line = next(ln for ln in (ROOT / "CLAUDE.md").read_text().splitlines() if ln.startswith("- Always allowed:"))
    head = line[len("- Always allowed:"):].split(".", 1)[0]
    return set(re.findall(r"`([A-Za-z]+)`", head))


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
        self.append({"type": "user", "message": {"role": "user", "content": "start"}, "version": "2.1.325"})

    def append(self, record: dict) -> None:
        record.setdefault("sessionId", self.sid)
        with self.transcript.open("a") as handle:
            handle.write(json.dumps(record) + "\n")

    def env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        env.update({"HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
                    "CLAUDE_STATE_DIR": str(self.state), "TMPDIR": str(self.tmp / "tmp"),
                    "CLAUDE_PROJECT_DIR": str(self.project), "GIT_CEILING_DIRECTORIES": str(self.tmp),
                    "PYTHONDONTWRITEBYTECODE": "1"})
        return env

    def run(self, hook: Path, event: str, **extra) -> subprocess.CompletedProcess:
        body = {"session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(self.project),
                "hook_event_name": event, "permission_mode": "default", **extra}
        return subprocess.run([sys.executable, str(hook)], input=json.dumps(body), capture_output=True,
                              text=True, env=self.env(), cwd=self.project, timeout=60)

    def gate(self, tool: str) -> subprocess.CompletedProcess:
        return self.run(GATE, "PreToolUse", tool_name=tool, tool_input=TOOL_INPUT[tool],
                        tool_use_id=f"toolu_{uuid.uuid4().hex[:20]}")

    def passes(self, tool: str, refusal: str = CAPPED) -> bool:
        p = self.gate(tool)
        assert p.returncode in (0, 2), (tool, p.returncode, p.stderr)
        if p.returncode == 2:
            assert refusal in p.stderr, (tool, p.stderr)
        return p.returncode == 0

    def prompt(self, text: str) -> None:
        """The next UserPromptSubmit through the registered prompt hook, then the record the CLI writes."""
        p = self.run(PROMPT_WORKFLOW, "UserPromptSubmit", prompt=text)
        assert p.returncode == 0, p.stderr
        self.append({"type": "user", "origin": {"kind": "human"}, "message": {"role": "user", "content": text}})

    def finished(self, tool: str) -> None:
        """The PostToolUse of a call that returned, through the grant consumer."""
        p = self.run(CONSUME, "PostToolUse", tool_name=tool, tool_input=TOOL_INPUT[tool],
                     tool_response={"success": True}, tool_use_id=f"toolu_{uuid.uuid4().hex[:20]}")
        assert p.returncode == 0, p.stderr

    def do_consent(self) -> None:
        (self.state / f"claude-orchestrator-consent-{self.sid}.flag").write_text("true")

    def grant_file(self) -> Path:
        return self.state / "claude-grants" / f"{self.sid}.json"

    def allow(self, tool: str) -> None:
        self.grant_file().parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        self.grant_file().write_text(json.dumps({
            "task_id": self.sid, "session_id": self.sid, "allowed_operations": [{"op": tool}],
            "created_at": now, "expires_at": now + 300}))

    def streak_file(self) -> Path:
        return self.state / f"claude-tool-streak-{self.sid}.json"

    def bash_count(self) -> dict:
        return json.loads(self.streak_file().read_text())["bash_consecutive"]


@pytest.fixture
def session(tmp_path):
    return Session(tmp_path)


# --- 1. The always-allowed set -------------------------------------------------------------------

def test_the_loaded_gate_runs_with_exactly_the_documented_set(tmp_path):
    """The set as the running module holds it, so a name added or dropped anywhere in the file (not
    only in the literal) breaks the agreement with CLAUDE.md."""
    probe = ("import importlib.util, json, sys\n"
             "spec = importlib.util.spec_from_file_location('gate', sys.argv[1])\n"
             "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
             "print(json.dumps({'allowed': sorted(m.ALWAYS_ALLOWED), 'capped': sorted(m.BASH_CAPPED),\n"
             "                  'blocked': sorted(m.PERMANENTLY_BLOCKED), 'cap': m.BASH_MAX_CONSECUTIVE}))\n")
    s = Session(tmp_path)
    p = subprocess.run([sys.executable, "-c", probe, str(GATE)], capture_output=True, text=True,
                       env=s.env(), cwd=s.project, timeout=60)
    assert p.returncode == 0, p.stderr
    loaded = json.loads(p.stdout)
    documented = documented_allowed()
    assert len(documented) == 16, sorted(documented)
    assert set(loaded["allowed"]) == documented, set(loaded["allowed"]) ^ documented
    assert loaded["capped"] == ["Bash", "Monitor"]
    assert loaded["blocked"] == list(PLAN_TOOLS)
    stated = re.search(r"`Bash` is capped at (\d+) calls: the (\d+)th", (ROOT / "CLAUDE.md").read_text())
    assert stated and (int(stated.group(1)), int(stated.group(2))) == (loaded["cap"], loaded["cap"] + 1)


@pytest.mark.parametrize("tool", sorted(documented_allowed() - {"Bash", "Monitor", "Agent"}))
def test_every_documented_name_passes_every_call_without_a_count(session, tool):
    for n in range(3):
        assert session.passes(tool), f"{tool} call {n + 1} in one turn"
    assert not session.streak_file().exists(), f"{tool} wrote a count"


@pytest.mark.parametrize("tool", ["Edit", "WebFetch", "TaskCreate"])
def test_a_name_off_the_list_passes_once_a_turn(session, tool):
    assert tool not in documented_allowed()
    assert session.passes(tool)
    assert not session.passes(tool), f"a second {tool} in one turn"


# --- 2. The Bash cap -----------------------------------------------------------------------------

def test_the_sixth_bash_is_refused_until_the_next_prompt(session):
    for _ in range(5):
        assert session.passes("Bash")
    p = session.gate("Bash")
    assert p.returncode == 2 and "Bash used consecutively beyond limit (6/5)" in p.stderr, p.stderr
    session.prompt("go on")
    for _ in range(5):
        assert session.passes("Bash"), "a Bash call after the next prompt"
    assert not session.passes("Bash")


def test_a_dispatch_resets_the_count_after_a_refusal(session):
    for _ in range(5):
        assert session.passes("Bash")
    assert not session.passes("Monitor")
    assert session.passes("Agent")
    assert session.bash_count() == {"last_tool": "Agent", "count": 0}
    for _ in range(5):
        assert session.passes("Bash")
    assert not session.passes("Bash")


@pytest.mark.parametrize("between", sorted(
    (documented_allowed() - {"Bash", "Monitor", "Agent"}) | {"Edit", "WebFetch", "TaskCreate", "EnterPlanMode"}))
def test_no_other_tool_resets_the_count(session, between):
    """Three Bash calls, then the other tool (allowed, counted or refused), then two more pass and the
    sixth Bash is refused: the count is 3, unchanged, across the other call."""
    for _ in range(3):
        assert session.passes("Bash")
    session.gate(between)
    session.gate(between)
    assert session.bash_count() == {"last_tool": "Bash", "count": 3}, f"{between} touched the count"
    for _ in range(2):
        assert session.passes("Bash")
    p = session.gate("Bash")
    assert p.returncode == 2 and "(6/5)" in p.stderr, (between, p.stderr)


# --- 3. EnterPlanMode / ExitPlanMode -------------------------------------------------------------

@pytest.mark.parametrize("tool", PLAN_TOOLS)
@pytest.mark.parametrize("consent", [False, True], ids=["plain", "under-do"])
def test_plan_mode_is_refused_on_every_call(session, tool, consent):
    if consent:
        session.do_consent()
        assert session.passes("Edit") and session.passes("Edit"), "/do lifts the once-per-turn limit"
    for n in range(3):
        p = session.gate(tool)
        assert p.returncode == 2, (n, p.stderr)
        assert f"{PERMANENT}: {tool} (/do does not unlock it)" in p.stderr, p.stderr
    if not consent:
        assert not session.streak_file().exists(), "a refused plan-mode call counts nothing"


@pytest.mark.parametrize("tool", PLAN_TOOLS)
@pytest.mark.parametrize("consent", [False, True], ids=["plain", "under-do"])
def test_an_allow_grant_naming_the_tool_passes_one_call(session, tool, consent):
    if consent:
        session.do_consent()
    other = next(t for t in PLAN_TOOLS if t != tool)
    session.allow(tool)
    assert not session.passes(other, PERMANENT), f"a grant naming {tool} passed {other}"
    assert session.grant_file().exists()
    assert session.passes(tool, PERMANENT), "the granted call"
    session.finished(tool)
    assert not session.grant_file().exists(), "the grant is spent by the call it let through"
    assert not session.passes(tool, PERMANENT), "a second call on one grant"


def test_a_grant_naming_another_tool_does_not_pass_plan_mode(session):
    session.allow("Monitor")
    for tool in PLAN_TOOLS:
        assert not session.passes(tool, PERMANENT)
