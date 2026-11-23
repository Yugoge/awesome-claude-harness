"""hooks/lib/dispatch_return.py: a dispatch's return inside a gated command carries the returned lane's
state and the Stop gate's open gaps, with the gate's own text; outside one nothing; the gate is bounded."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
sys.path.insert(0, str(REPO))
from tests.cli_shapes import synthesize  # noqa: E402

SID = "11111111-2222-3333-4444-555555555555"
TASK = "dev-20261101-090000-l1"
REPORT = "docs/dev/dev-report-20261101-090000-l1.json"


def _module():
    spec = importlib.util.spec_from_file_location("dispatch_return_under_test", HOOKS / "lib" / "dispatch_return.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prompt() -> str:
    ob = {"task_id": TASK, "lane": "l1", "role": "dev", "pipeline": "dev", "profile": "fanout-lane",
          "artifacts": [{"kind": "json", "path": REPORT, "schema": "dev-report.v2", "identity": {"task_id": TASK}}]}
    return f"Lane l1: fix the parser.\n<obligation v=\"1\">\n{json.dumps(ob)}\n</obligation>\n"


def _transcript(path: Path, opener: str | None, tool_input: dict) -> str:
    def add(record):
        record["sessionId"] = SID
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        return record
    path.write_text("", encoding="utf-8")
    if opener:
        add(synthesize("queue-operation", "enqueue", content=f"/{opener} fix the parser"))
        head = add(synthesize("user", "command", turnOrigin="human", message__content=(
            f"<command-message>{opener} is running…</command-message>\n<command-name>/{opener}</command-name>\n"
            "<command-args>fix the parser</command-args>")))
        add(synthesize("user", "meta", parentUuid=head["uuid"], message__content=[{"type": "text", "text": "body"}]))
    else:
        add(synthesize("user", "prompt", turnOrigin="human", message__content="fix the parser"))
    add(synthesize("assistant", "tool_use", message__content=[
        {"type": "tool_use", "id": "toolu_0001", "name": "Agent", "input": tool_input}]))
    add(synthesize("user", "tool_result", message__content=[
        {"type": "tool_result", "tool_use_id": "toolu_0001", "content": "done", "is_error": False}]))
    return str(path)


@pytest.fixture
def env(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "docs" / "dev").mkdir(parents=True)
    for name in ("HOME", "CLAUDE_STATE_DIR", "TMPDIR"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(name, str(tmp_path / name))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.delenv("CLAUDE_COMMAND_GATE", raising=False)
    return tmp_path, project


def _payload(tmp_path, opener, background=False, **extra):
    tool_input = {"subagent_type": "dev", "description": "lane l1", "prompt": _prompt(),
                  **({"run_in_background": True} if background else {})}
    return {"session_id": SID, "transcript_path": _transcript(tmp_path / "t.jsonl", opener, tool_input),
            "cwd": os.environ["CLAUDE_PROJECT_DIR"], "hook_event_name": "PostToolUse", "tool_name": "Agent",
            "tool_use_id": "toolu_0001", "tool_input": tool_input,
            "tool_response": {"status": "async_launched"} if background else {"status": "completed"}, **extra}


def _stop_text(payload) -> str:
    stop = {k: payload[k] for k in ("session_id", "transcript_path", "cwd")} | {"hook_event_name": "Stop"}
    return subprocess.run([sys.executable, str(HOOKS / "stop-command-gate.py"), "--mode", "block"],
                          input=json.dumps(stop), capture_output=True, text=True, timeout=120).stderr


def _main_output(module, payload, monkeypatch) -> str:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    assert module.main() == 0
    return out.getvalue()


def test_a_return_inside_a_gated_command_carries_the_lane_state_and_the_stop_gates_gaps(env, monkeypatch):
    tmp_path, project = env
    (project / REPORT).write_text(json.dumps({"dev": {"status": "completed", "files_modified": ["src/gone.py"],
                                                      "files_created": []},
                                              "blocking_issues": ["parser rejects the empty case"]}))
    payload = _payload(tmp_path, "dev")
    out = json.loads(_main_output(_module(), payload, monkeypatch))["hookSpecificOutput"]
    assert out["hookEventName"] == "PostToolUse"
    text = out["additionalContext"]
    state, _, rest = text.partition("\n- ")
    assert state == f"Returned dispatch (dev, lane l1, task {TASK}):"
    line, _, gaps = rest.partition("\n")
    assert line == (f"{REPORT}: dev.status 'completed'; blocking_issues 1: parser rejects the empty case; "
                    "declared paths absent 1: src/gone.py")
    stop = _stop_text(payload)
    assert stop.startswith("COMMAND_GATE /dev: not complete\n")
    assert gaps == stop  # the same predicate, the same wording, the same bound (the gate's own BLOCK_BOUND)


def test_an_absent_report_and_a_prompt_without_obligation_are_named(env):
    tmp_path, _ = env
    module = _module()
    payload = _payload(tmp_path, "dev")
    assert module.handback(payload).startswith(
        f"Returned dispatch (dev, lane l1, task {TASK}):\n- {REPORT}: absent\nCOMMAND_GATE /dev")
    payload["tool_input"] = {"subagent_type": "qa", "prompt": "check it"}
    assert module.handback(payload).startswith("Returned dispatch (qa): declares no report (no obligation block)\n")


@pytest.mark.parametrize("opener", [None, "spec", "tickets"])
def test_outside_a_gated_command_nothing_is_added(env, monkeypatch, opener):
    tmp_path, _ = env
    module = _module()
    assert _main_output(module, _payload(tmp_path, opener), monkeypatch) == ""
    assert module.handback(_payload(tmp_path, opener)) is None


def test_a_subagents_own_dispatch_gets_nothing(env):
    assert _module().handback(_payload(env[0], "dev", agent_id="a1")) is None


def test_a_background_dispatch_gets_it_from_the_function_at_its_end_not_at_its_launch(env, monkeypatch):
    module = _module()
    payload = _payload(env[0], "dev", background=True)
    assert _main_output(module, payload, monkeypatch) == ""
    assert module.handback(payload).startswith(f"Returned dispatch (dev, lane l1, task {TASK}):")


def test_a_gate_past_the_bound_is_one_line_and_does_not_hold_the_return(env, tmp_path):
    module = _module()
    slow = tmp_path / "slow-gate.py"
    ended = tmp_path / "gate-ended"
    slow.write_text("import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', 'import time; "
                    "time.sleep(120)'])\ntime.sleep(120)\n"
                    f"open({str(ended)!r}, 'w').close()\n")
    module.GATE, module.BOUND = str(slow), 1.0
    # No wall time is compared: the return must come while the gate is still asleep (no marker). A
    # return that waits for the gate would take its whole 300 s.
    text = module.handback(_payload(env[0], "dev"))
    assert not ended.exists(), "the return waited for the gate to end"
    tail = text.splitlines()[-1]
    assert tail == "COMMAND_GATE open gaps not listed: the Stop gate took over 1 s; they are listed at the Stop."


def test_the_gate_off_adds_the_lane_state_only(env, monkeypatch):
    monkeypatch.setenv("CLAUDE_COMMAND_GATE", "off")
    text = _module().handback(_payload(env[0], "dev"))
    assert "COMMAND_GATE" not in text and text.startswith("Returned dispatch (dev, lane l1")


def test_the_rule_runs_after_every_dispatch_tool_in_the_post_tool_launcher():
    launcher = (HOOKS / "posttool-launch.py").read_text()
    assert "Rule('dispatch-return', 'lib/dispatch_return.py', DISPATCH_TOOLS, timeout=30)" in launcher
    assert _module().BOUND < 30
