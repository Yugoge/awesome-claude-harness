"""P2-9: the orchestrator gate's per-turn budget inside an unattended /dev-overnight session.

hooks/pretool-orchestrator-gate.py allows the main agent one call per non-whitelisted tool name per
turn, and only hooks/prompt-workflow.py's UserPromptSubmit resets that count. A /dev-overnight session
gets no prompt all night (one turn), so every main-agent Write or Edit after the first was refused
until the session ended (PR #22 c6722563252: "Write used consecutively beyond limit" (3/1) to (8/1)).

Inside the session's open overnight window (lib/overnight.window_open: its own record, end_time
ahead, no human-typed /stop after its /dev-overnight) an Agent dispatch now also resets the per-tool
counts, as it resets Bash's streak: between two dispatches the budget is still one call per tool
name. Outside the window (an interactive turn, after the owner's /stop, after end_time, another
session's record) an Agent dispatch resets nothing but Bash's streak, as before.

Each hook runs as a subprocess with a PreToolUse payload as the CLI sends it, its state dir, HOME,
project and TMPDIR inside the test's tmp_path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "hooks" / "pretool-orchestrator-gate.py"
REFUSED = "used consecutively beyond limit"


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


class Session:
    def __init__(self, tmp_path: Path, first_prompt: str):
        self.tmp, self.sid = tmp_path, str(uuid.uuid4())
        self.home = tmp_path / "home"
        self.project = tmp_path / "project"
        self.state = tmp_path / "state"
        for d in (self.project / ".claude", self.state, tmp_path / "tmp"):
            d.mkdir(parents=True, exist_ok=True)
        tdir = self.home / ".claude" / "projects" / "-project"
        tdir.mkdir(parents=True)
        self.transcript = tdir / f"{self.sid}.jsonl"
        self.transcript.write_text("")
        self.typed(first_prompt)
        self.files = 0

    def typed(self, text: str) -> None:
        with self.transcript.open("a") as handle:
            handle.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")

    def record(self, sid: str | None = None, end: timedelta = timedelta(hours=1)) -> None:
        """The launcher's overnight-state record of ``sid`` (this session's by default)."""
        sid = sid or self.sid
        (self.project / ".claude" / f"overnight-state-{sid}.json").write_text(json.dumps({
            "session_id": sid, "start_time": _iso(timedelta(hours=-1)), "end_time": _iso(end),
            "current_phase": "exploring"}))

    def gate(self, tool: str, tool_input: dict | None = None) -> subprocess.CompletedProcess:
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
               "CLAUDE_STATE_DIR": str(self.state), "TMPDIR": str(self.tmp / "tmp"),
               "CLAUDE_PROJECT_DIR": str(self.project), "GIT_CEILING_DIRECTORIES": str(self.tmp),
               "PYTHONDONTWRITEBYTECODE": "1"}
        body = {"session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(self.project),
                "hook_event_name": "PreToolUse", "permission_mode": "default", "tool_name": tool,
                "tool_input": tool_input or {}}
        return subprocess.run([sys.executable, str(GATE)], input=json.dumps(body), capture_output=True,
                              text=True, env=env, cwd=self.project, timeout=60)

    def write(self) -> subprocess.CompletedProcess:
        """A Write of a new file (a Write over an existing file is never counted)."""
        self.files += 1
        return self.gate("Write", {"file_path": str(self.project / f"new-{self.files}.md"), "content": "x"})

    def edit(self) -> subprocess.CompletedProcess:
        return self.gate("Edit", {"file_path": str(self.project / "a.md"), "old_string": "a", "new_string": "b"})

    def dispatch(self) -> None:
        p = self.gate("Agent", {"subagent_type": "general-purpose", "prompt": "x", "run_in_background": False})
        assert p.returncode == 0, p.stderr

    def streak(self) -> dict:
        return json.loads((self.state / f"claude-tool-streak-{self.sid}.json").read_text())


def _allowed(p: subprocess.CompletedProcess) -> bool:
    assert p.returncode in (0, 2), (p.returncode, p.stderr)
    if p.returncode == 2:
        assert REFUSED in p.stderr, p.stderr
    return p.returncode == 0


@pytest.fixture
def night(tmp_path):
    s = Session(tmp_path, "/dev-overnight 1h harden the toy package")
    s.record()
    return s


def test_overnight_second_write_and_edit_allowed_after_a_dispatch(night):
    assert _allowed(night.write()) and _allowed(night.edit())
    night.dispatch()
    assert _allowed(night.write()), "a Write after a dispatch inside the overnight window"
    assert _allowed(night.edit()), "an Edit after a dispatch inside the overnight window"
    night.dispatch()
    assert _allowed(night.write()) and _allowed(night.edit())


def test_overnight_budget_between_two_dispatches_stays_one_per_tool(night):
    """The boundary is the dispatch: before it, the turn's second Write and Edit are refused as ever."""
    assert _allowed(night.write())
    assert not _allowed(night.write())
    assert _allowed(night.edit())
    assert not _allowed(night.edit())
    night.dispatch()
    assert _allowed(night.write())
    assert not _allowed(night.write())


def test_overnight_dispatch_still_resets_bash_and_only_the_counts(night):
    for _ in range(3):
        assert night.gate("Bash", {"command": "true"}).returncode == 0
    assert _allowed(night.write())
    night.dispatch()
    assert night.streak() == {"schema_version": 2, "per_tool_counts": {},
                              "bash_consecutive": {"last_tool": "Agent", "count": 0}}


def test_interactive_turn_second_write_still_refused_after_a_dispatch(tmp_path):
    s = Session(tmp_path, "/dev fix the bug")
    assert _allowed(s.write()) and _allowed(s.edit())
    s.dispatch()
    assert not _allowed(s.write()), "an interactive turn's second Write"
    assert not _allowed(s.edit()), "an interactive turn's second Edit"
    assert s.streak()["per_tool_counts"] == {"Write": 2, "Edit": 2}


def test_after_the_owners_stop_a_dispatch_resets_nothing(night):
    night.typed("/stop")
    assert _allowed(night.write())
    night.dispatch()
    assert not _allowed(night.write())


def test_after_end_time_a_dispatch_resets_nothing(night):
    night.record(end=timedelta(minutes=-1))
    assert _allowed(night.write())
    night.dispatch()
    assert not _allowed(night.write())


def test_another_sessions_overnight_record_resets_nothing(tmp_path):
    s = Session(tmp_path, "/dev-overnight 1h harden the toy package")
    s.record(sid=str(uuid.uuid4()))
    assert _allowed(s.write())
    s.dispatch()
    assert not _allowed(s.write())
