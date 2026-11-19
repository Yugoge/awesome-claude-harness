#!/usr/bin/env python3
"""The /dev-overnight dispatch contract binds the /dev-overnight span only.

pretool-subagent-enforce.py reads the in-progress step label of the active
span's checklist and validates the Agent against /dev-overnight's steps. A
/dev checklist reuses the same labels ("Step 4: Requirement round" against
"Step 4: PM Triage"), so the contract applies only while the active span is
the human-typed /dev-overnight's:

- a /dev the owner types after the window ended, or mid live window, is its
  own span: its Step 4 BA intake passes (directly and through the registered
  pretool-launch.py);
- inside the /dev-overnight span the contract still holds: Step 4 PM Triage
  refuses a BA (CONTRACT BLOCK), in a live window and after end_time (the
  closeout steps still run under it);
- nothing but a human-typed command opens a span: a plain prompt, a
  Skill-tool expansion or a scheduled prompt carrying "/dev x" leaves the
  overnight span active, so the contract still refuses there;
- a /dev-overnight span with no checklist yet enforces nothing here (no step
  to read), the same as before; the dispatch is refused by the todo gate.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
REPO = HOOKS.parent
SID = "sess-span-scope"
TASK = "20261117-080000"
GIT_ENV = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}
ENDED, LIVE = -60, 360  # end_time, minutes from now


def _iso(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _todos(command: str, active: int) -> list:
    out = subprocess.run([sys.executable, str(REPO / "scripts" / "todo" / f"{command}.py")],
                         capture_output=True, text=True, timeout=30,
                         env={**os.environ, "CLAUDE_TODO_PROMPT": "x"}).stdout
    return [{**s, "status": "completed" if k < active else ("in_progress" if k == active else "pending")}
            for k, s in enumerate(json.loads(out))]


def _index(command: str, label: str) -> int:
    return next(k for k, s in enumerate(_todos(command, -1)) if s["content"].startswith(f"Step {label}:"))


class _Transcript:
    def __init__(self, root: Path):
        self.root, self.records, self.n = root, [], 0

    def command(self, name: str, args: str = "x", **extra):
        self.records.append({"type": "user", "uuid": f"u{len(self.records)}", **extra, "message": {
            "role": "user", "content": f"<command-message>{name}</command-message>\n"
                                       f"<command-name>/{name}</command-name>\n<command-args>{args}</command-args>"}})

    def prompt(self, text: str, **extra):
        self.records.append({"type": "user", "uuid": f"u{len(self.records)}", **extra,
                             "message": {"role": "user", "content": text}})

    def checklist(self, command: str, label: str | None):
        self.n += 1
        todos = _todos(command, -1 if label is None else _index(command, label))
        self.records.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": f"tw{self.n}", "name": "TodoWrite", "input": {"todos": todos}}]}})
        self.records.append({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"tw{self.n}", "content": "ok"}]}, "toolUseResult": "ok"})

    def write(self) -> Path:
        path = self.root / "transcript.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in self.records))
        return path


@pytest.fixture
def session(tmp_path):
    # The project outside /tmp and /var/tmp, where BA may write its requirement round (the dispatch
    # check of pretool-tool-policy.py refuses a dispatch whose declared file its role could not write).
    from test_report_provenance_gate import project_outside_temp
    with project_outside_temp() as outside:
        yield _maker(outside.parent)


def _maker(base: Path):
    def make(end_minutes: int) -> _Transcript:
        root = base / "main"
        root.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "trunk"], cwd=root, env=GIT_ENV, check=True)
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=root, env=GIT_ENV, check=True)
        (root / ".claude").mkdir()
        (root / ".claude" / f"overnight-state-{SID}.json").write_text(json.dumps({
            "session_id": SID, "start_time": _iso(-600), "end_time": _iso(end_minutes),
            "current_phase": "exploring", "isolation_active_until": _iso(end_minutes),
            "isolation_released_at": None, "protected_branch": "trunk", "main_root": str(root),
            "worktree_path": str(root), "addressed_issues": []}))
        t = _Transcript(root)
        t.command("dev-overnight", "2h")
        return t
    return make


def _ba() -> dict:
    obligation = {"task_id": TASK, "lane": None, "lane_set": None, "role": "ba", "pipeline": "dev",
                  "profile": "singular", "dispatched_at": _iso(0),
                  "artifacts": [{"kind": "json", "path": f"docs/dev/requirement-round-{TASK}-r1.json",
                                 "schema": "requirement-round.v1", "identity": {"task_id": TASK}}]}
    return {"subagent_type": "ba", "description": "BA intake", "run_in_background": False,
            "prompt": f'<obligation v="1">{json.dumps(obligation)}</obligation>\nRequirement round 1 for: x'}


def _run(t: _Transcript, hook: str, tool_input: dict | None = None):
    path = t.write()
    payload = {"session_id": SID, "transcript_path": str(path), "cwd": str(t.root),
               "hook_event_name": "PreToolUse", "tool_name": "Agent",
               "tool_input": tool_input or _ba(), "tool_use_id": "toolu_scope"}
    return subprocess.run([sys.executable, str(HOOKS / hook)], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(t.root), timeout=120,
                          env={**os.environ, "CLAUDE_PROJECT_DIR": str(t.root)})


ENFORCE, LAUNCH = "pretool-subagent-enforce.py", "pretool-launch.py"


# --------------------------------------------------------------------------
# Must pass: a /dev the owner typed is its own span
# --------------------------------------------------------------------------

@pytest.mark.parametrize("end", [ENDED, LIVE], ids=["window-ended", "live-window"])
@pytest.mark.parametrize("hook", [ENFORCE, LAUNCH])
def test_an_owner_typed_dev_is_not_held_to_the_overnight_contract(session, end, hook):
    t = session(end)
    t.checklist("dev-overnight", "2")
    t.command("dev", "x")
    t.checklist("dev", "4")
    result = _run(t, hook)
    assert "CONTRACT BLOCK" not in result.stderr, result.stderr
    assert result.returncode == 0, result.stderr + result.stdout


def test_a_dev_after_stop_is_not_held_to_the_overnight_contract(session):
    t = session(LIVE)
    t.checklist("dev-overnight", "4")
    t.command("stop", "")
    t.command("dev", "x")
    t.checklist("dev", "4")
    result = _run(t, ENFORCE)
    assert result.returncode == 0 and "CONTRACT BLOCK" not in result.stderr, result.stderr


# --------------------------------------------------------------------------
# Must still refuse: the /dev-overnight span keeps its contract
# --------------------------------------------------------------------------

@pytest.mark.parametrize("end", [ENDED, LIVE], ids=["window-ended", "live-window"])
@pytest.mark.parametrize("hook", [ENFORCE, LAUNCH])
def test_the_overnight_span_at_pm_triage_refuses_a_ba(session, end, hook):
    t = session(end)
    t.checklist("dev-overnight", "4")
    result = _run(t, hook)
    assert result.returncode == 2, result.stderr
    assert "CONTRACT BLOCK" in result.stderr
    assert "role mismatch on step '4'" in result.stderr


def test_a_dev_overnight_typed_after_a_dev_holds_the_contract_again(session):
    t = session(LIVE)
    t.command("dev", "x")
    t.checklist("dev", "4")
    t.command("dev-overnight", "2h")
    t.checklist("dev-overnight", "4")
    result = _run(t, ENFORCE)
    assert result.returncode == 2 and "CONTRACT BLOCK" in result.stderr


FORGED = {
    "plain-prompt": lambda t: t.prompt("please run /dev x now"),
    "skill-expansion": lambda t: t.command("dev", "x", isMeta=True, sourceToolUseID="toolu_skill"),
    "scheduled-prompt": lambda t: t.prompt("/dev x", origin={"kind": "scheduled"}),
    "subagent-record": lambda t: t.command("dev", "x", isSidechain=True),
}


@pytest.mark.parametrize("forge", sorted(FORGED))
def test_no_record_but_a_human_typed_command_lifts_the_contract(session, forge):
    t = session(LIVE)
    t.checklist("dev-overnight", "2")
    FORGED[forge](t)
    t.checklist("dev-overnight", "4")
    result = _run(t, ENFORCE)
    assert result.returncode == 2 and "CONTRACT BLOCK" in result.stderr, (forge, result.stderr)


def test_an_overnight_span_with_no_checklist_yet(session):
    t = session(LIVE)
    # No step to read: this hook enforces nothing, as before (fail open by design) ...
    assert _run(t, ENFORCE).returncode == 0
    # ... and the registered pipeline still refuses the dispatch.
    launched = _run(t, LAUNCH)
    assert launched.returncode == 2, launched.stderr + launched.stdout
    assert "CHECKLIST NOT STARTED" in launched.stderr
