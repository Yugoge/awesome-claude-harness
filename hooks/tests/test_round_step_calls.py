"""The requirement round's step states every call of the round, each with its own role (scripts/todo/dev.py
ROUND_CALLS, shared by /dev-command and, through dev.py, /redev).

1. Gate 4 (hooks/pretool-todo-validate.py) holds Step 4 until the BA analysis call (role ba, `Mode: analysis`)
   came back in it: the panel's three ba calls and panel QA, or the intake's ba call, never stand in for it.
2. Panel QA's template (ba-panel-<ts>-r1.json, role qa) binds to Step 4 with its own role, and the dispatch gate
   (hooks/pretool-obligation-gate.py) passes its dispatch as qa and refuses it as another role.
3. A complete round still passes.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
ROOT = HOOKS.parent
sys.path.insert(0, str(ROOT))
from hooks.lib import obligation  # noqa: E402


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


flight = _module("_round_in_flight", HOOKS / "tests" / "test_todo_validate_in_flight.py")
gate = _module("_round_obligation_gate", HOOKS / "tests" / "test_obligation_gate.py")
TASK = "20261122-090000"


def _prompt(mode_line):
    return f"You are the subagent.\n{mode_line}\nRequirement: 'x'\n"


def _call(s, subagent_type, mode_line):
    tid = s.use("Agent", {"subagent_type": subagent_type, "prompt": _prompt(mode_line), "description": "x"})
    s.result(tid)


def _at_round(s, command):
    s.command(command, "build it", flight._current_text(command, "build it"))
    four = flight._i(s.steps, "Step 4")
    s.walk(four)
    return four


PANEL = [("ba", "Mode: panel")] * 3 + [("qa", "You are the QA subagent in PANEL QA MODE.")]
INTAKE = [("ba", "Mode: intake")]


@pytest.mark.parametrize("command", ["dev", "dev-command"])
@pytest.mark.parametrize("round_calls", [PANEL, INTAKE], ids=["panel", "intake"])
def test_the_round_step_waits_for_the_ba_analysis_call(flight_session, command, round_calls):
    s = flight_session
    four = _at_round(s, command)
    for kind, line in round_calls:
        _call(s, kind, line)
    refused = s.todo(flight._done(s.steps, four))
    assert refused.returncode == 2 and 'ba with "Mode: analysis"' in refused.stderr, refused.stderr
    _call(s, "ba", "Mode: analysis")
    done = s.todo(flight._done(s.steps, four))  # (3) the complete round passes
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("command", ["dev", "dev-command"])
def test_a_qa_or_a_modeless_ba_call_is_not_the_analysis(flight_session, command):
    s = flight_session
    four = _at_round(s, command)
    _call(s, "qa", "Mode: analysis")
    _call(s, "ba", "Requirement only")
    assert s.todo(flight._done(s.steps, four)).returncode == 2


@pytest.fixture
def flight_session(tmp_path):
    return flight._Session(tmp_path)


@pytest.mark.parametrize("command", ["dev", "dev-command", "redev"])
def test_the_round_step_states_each_call_with_its_own_role(command):
    step = next(s for s in flight._canonical(command) if s["content"].startswith("Step 4:"))
    calls = [(c["subagent_type"], c["prompt_mode"], bool(c.get("optional"))) for c in step["subagent_call"]]
    assert calls == [("ba", "intake", True), ("ba", "panel", True), ("qa", "panel", True), ("ba", "analysis", False)]


def _panel_qa_prompt(command):
    """Panel QA's dispatch as the command's own template gives it, its placeholders filled in."""
    text = (ROOT / "commands" / f"{command}.md").read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if 'role="qa"' in l and "ba-panel-<timestamp>-r1.json" in l)
    artifacts = json.loads(re.search(r"artifacts=(\[.*\])\.", line).group(1).replace("<timestamp>", TASK))
    pipeline = re.search(r'pipeline="([^"]+)"', line).group(1)
    doc = gate._obligation_doc(role="qa", pipeline=pipeline, profile="ba_validation", artifacts=artifacts,
                               task_id=TASK)
    return "You are the QA subagent in PANEL QA MODE.\n" + gate._block(doc)


@pytest.mark.parametrize("command", ["dev", "dev-command"])
def test_panel_qa_s_template_binds_to_the_round_step_with_its_own_role(command):
    answer = obligation._canonical_step(TASK, f"docs/dev/ba-panel-{TASK}-r1.json", [(command, "")], [command])
    assert answer["step"].startswith("Step 4:"), answer["step"]
    assert answer["template"]["role"] == "qa"
    assert "qa" in {c["subagent_type"] for c in answer["subagent_call"]}


@pytest.mark.parametrize("command", ["dev", "dev-command"])
@pytest.mark.parametrize("subagent_type,code", [("qa", 0), ("ba", 2)])
def test_panel_qa_s_dispatch_passes_as_qa_and_is_refused_as_another_role(tmp_path, command, subagent_type, code):
    home, project = gate._dirs(tmp_path)
    payload = gate._dispatch_payload(project, gate._unique_sid("panelqa"), gate._span_records(command),
                                     subagent_type=subagent_type, prompt=_panel_qa_prompt(command))
    result = gate._run_hook(home, project, payload, switch="block")
    assert result.returncode == code, result.stderr
    assert ("role_mismatch" in result.stderr) == (code == 2), result.stderr
