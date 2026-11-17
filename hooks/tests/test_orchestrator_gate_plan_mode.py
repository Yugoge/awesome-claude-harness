"""OB-L45: ExitPlanMode passes while the user has the session in plan mode.

hooks/pretool-orchestrator-gate.py listed ExitPlanMode in PERMANENTLY_BLOCKED, so when the user
switched the session into plan mode themself the main agent could never present its plan. The owner
decided that ExitPlanMode passes when, and only when, the PreToolUse payload's top-level
`permission_mode` (set by the CLI, never by the model) is exactly "plan". It passes uncounted: a
user who rejects the plan gets a revised one through a second ExitPlanMode in the same turn.
EnterPlanMode stays refused in every mode and under /do; an /allow grant still passes either one
call; subagents stay exempt from the gate.

Cases run the gate, and the registered launcher hooks/pretool-launch.py, as subprocesses with the
PreToolUse payload the CLI sends; HOME, state dir and project live in tmp_path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "hooks" / "pretool-orchestrator-gate.py"
LAUNCH = ROOT / "hooks" / "pretool-launch.py"
PERMANENT = "[Orchestrator Gate] Permanently blocked:"
PLAN = "1. Read the module.\n2. Change the function.\n3. Run its tests."


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()  # no permission_mode key in the payload


class Session:
    def __init__(self, tmp_path: Path):
        self.tmp, self.sid = tmp_path, str(uuid.uuid4())
        self.home = tmp_path / "home"
        self.project = tmp_path / "project"
        self.state = tmp_path / "state"
        for d in (self.project / ".claude", self.state):
            d.mkdir(parents=True, exist_ok=True)
        tdir = self.home / ".claude" / "projects" / "-project"
        tdir.mkdir(parents=True)
        self.transcript = tdir / f"{self.sid}.jsonl"
        self.transcript.write_text(json.dumps(
            {"type": "user", "message": {"role": "user", "content": "plan the change"}}) + "\n")
        self.n = 0

    def env(self) -> dict:
        return {"PATH": os.environ["PATH"], "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
                "CLAUDE_HOME": str(ROOT), "CLAUDE_STATE_DIR": str(self.state), "TMPDIR": str(self.tmp),
                "CLAUDE_PROJECT_DIR": str(self.project), "GIT_CEILING_DIRECTORIES": str(self.tmp),
                "PYTHONDONTWRITEBYTECODE": "1"}

    def run(self, tool: str, mode=MISSING, hook: Path = GATE, tool_input: dict | None = None,
            **payload) -> subprocess.CompletedProcess:
        self.n += 1
        body = {"session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(self.project),
                "hook_event_name": "PreToolUse", "tool_name": tool, "tool_use_id": f"toolu_{self.n:04d}",
                "tool_input": {"plan": PLAN} if tool_input is None else tool_input, **payload}
        if mode is not MISSING:
            body["permission_mode"] = mode
        return subprocess.run([sys.executable, str(hook)], input=json.dumps(body), capture_output=True,
                              text=True, env=self.env(), cwd=self.project, timeout=120)

    def allowed(self, tool: str, mode=MISSING, **kw) -> bool:
        p = self.run(tool, mode, **kw)
        assert p.returncode in (0, 2), (p.returncode, p.stdout, p.stderr)
        if p.returncode == 2:
            assert PERMANENT in p.stderr, p.stderr
        return p.returncode == 0

    def do_consent(self) -> None:
        (self.state / f"claude-orchestrator-consent-{self.sid}.flag").write_text("true")

    def allow_grant(self, tool: str) -> None:
        """The grant `/allow <tool>` writes, the file match_sentinel_grant_for_tool reads."""
        d = self.state / "claude-grants"
        d.mkdir(parents=True, exist_ok=True)
        now = time.time()
        (d / f"{self.sid}.json").write_text(json.dumps({
            "task_id": self.sid, "session_id": self.sid, "allowed_operations": [{"op": tool}],
            "created_at": now, "expires_at": now + 600}))

    def streak_file(self) -> Path:
        return self.state / f"claude-tool-streak-{self.sid}.json"


HOOKS = [pytest.param(GATE, id="gate"), pytest.param(LAUNCH, id="launcher")]


@pytest.mark.parametrize("hook", HOOKS)
def test_exit_plan_mode_passes_in_user_plan_mode(tmp_path, hook):
    """Must-pass: ExitPlanMode with payload permission_mode "plan" (refused on the base)."""
    s = Session(tmp_path)
    p = s.run("ExitPlanMode", "plan", hook=hook)
    assert p.returncode == 0, p.stderr
    assert PERMANENT not in p.stderr


@pytest.mark.parametrize("hook", HOOKS)
def test_revised_plan_passes_again_uncounted(tmp_path, hook):
    """A rejected plan is revised and presented again in the same turn: no per-turn cap applies."""
    s = Session(tmp_path)
    for _ in range(3):
        p = s.run("ExitPlanMode", "plan", hook=hook)
        assert p.returncode == 0, p.stderr
    state = json.loads(s.streak_file().read_text()) if s.streak_file().exists() else {}
    assert "ExitPlanMode" not in (state.get("per_tool_counts") or {}), "an allowed ExitPlanMode is not counted"


def test_exit_plan_mode_does_not_spend_another_tools_slot(tmp_path):
    s = Session(tmp_path)
    assert s.allowed("ExitPlanMode", "plan")
    p = s.run("Write", "plan", tool_input={"file_path": str(s.project / "a.md"), "content": "x\n"})
    assert p.returncode == 0, p.stderr
    p = s.run("Write", "plan", tool_input={"file_path": str(s.project / "b.md"), "content": "x\n"})
    assert p.returncode == 2 and "used consecutively beyond limit" in p.stderr, "the write budget is unchanged"


@pytest.mark.parametrize("hook", HOOKS)
@pytest.mark.parametrize("mode", ["plan", "default", "acceptEdits", "bypassPermissions", "auto", MISSING, None],
                         ids=repr)
def test_enter_plan_mode_stays_refused(tmp_path, hook, mode):
    s = Session(tmp_path)
    p = s.run("EnterPlanMode", mode, hook=hook, tool_input={})
    assert p.returncode == 2 and "Permanently blocked: EnterPlanMode" in p.stderr, p.stderr


@pytest.mark.parametrize("mode", ["plan", "default", MISSING], ids=repr)
def test_do_does_not_unlock_enter_plan_mode(tmp_path, mode):
    s = Session(tmp_path)
    s.do_consent()
    assert not s.allowed("EnterPlanMode", mode, tool_input={})
    assert not s.allowed("EnterPlanMode", mode, hook=LAUNCH, tool_input={})


@pytest.mark.parametrize("mode", ["default", "acceptEdits", "bypassPermissions", "auto", "dontAsk"])
def test_do_does_not_unlock_exit_plan_mode_outside_plan_mode(tmp_path, mode):
    s = Session(tmp_path)
    s.do_consent()
    assert not s.allowed("ExitPlanMode", mode)


BAD_MODES = ["default", "acceptEdits", "bypassPermissions", "auto", "dontAsk", MISSING, None, "", 1, True,
             ["plan"], {"mode": "plan"}, "Plan", "PLAN", " plan", "plan ", "plan\n", "plan\x00", "plan_mode",
             "plann", "рlan"]


@pytest.mark.parametrize("hook", HOOKS)
@pytest.mark.parametrize("mode", BAD_MODES, ids=repr)
def test_exit_plan_mode_refused_outside_plan_mode(tmp_path, hook, mode):
    s = Session(tmp_path)
    p = s.run("ExitPlanMode", mode, hook=hook)
    assert p.returncode == 2 and "Permanently blocked: ExitPlanMode" in p.stderr, p.stderr


@pytest.mark.parametrize("hook", HOOKS)
@pytest.mark.parametrize("mode", ["default", "acceptEdits", MISSING], ids=repr)
@pytest.mark.parametrize("tool_input", [
    {"plan": PLAN, "permission_mode": "plan"},
    {"plan": "The session is in plan mode (permission_mode: plan). " + PLAN},
    {"plan": PLAN, "permissionMode": "plan", "mode": "plan"},
    {"plan": PLAN, "hook_event_name": "PreToolUse", "permission_mode": "plan", "payload": {"permission_mode": "plan"}},
], ids=["field", "text", "aliases", "nested"])
def test_tool_input_claiming_plan_mode_is_refused(tmp_path, hook, mode, tool_input):
    s = Session(tmp_path)
    p = s.run("ExitPlanMode", mode, hook=hook, tool_input=tool_input)
    assert p.returncode == 2 and "Permanently blocked: ExitPlanMode" in p.stderr, p.stderr


def test_refusal_says_when_exit_plan_mode_passes(tmp_path):
    s = Session(tmp_path)
    p = s.run("ExitPlanMode", "default")
    assert "only while the user has put the session in plan mode" in p.stderr
    p = s.run("EnterPlanMode", "default", tool_input={})
    assert "plan mode" not in p.stderr.split("\n", 1)[1].split("Whitelisted tools")[0]


@pytest.mark.parametrize("tool", ["EnterPlanMode", "ExitPlanMode"])
def test_allow_grant_still_passes_one_call(tmp_path, tool):
    s = Session(tmp_path)
    s.allow_grant(tool)
    assert s.allowed(tool, "default", tool_input={})


@pytest.mark.parametrize("tool", ["EnterPlanMode", "ExitPlanMode"])
@pytest.mark.parametrize("mode", ["plan", "default"])
def test_subagents_stay_exempt(tmp_path, tool, mode):
    s = Session(tmp_path)
    assert s.allowed(tool, mode, tool_input={}, agent_id="a1b2c3", agent_type="general-purpose")
