"""Background dispatch (the owner's five decisions of 2026-11-21), one group per decision.

1. hooks/pretool-block-background-tasks.py lets the orchestrator dispatch any role in the
   background, inside or outside any command, /dev-overnight included; a background shell and
   the Workflow tool stay refused.
2. hooks/pretool-orchestrator-gate.py: a background launch resets no call limit.
3. hooks/prompt-workflow.py: a task-notification wake resets no limit and keeps the /do consent.
4. hooks/stop-command-gate.py: a stop while a background child of the span runs passes as a wait
   that says what it waits for; with none running (none launched, it completed, failed or was
   stopped) it blocks as before.
5. hooks/posttool-dispatch-record.py: at a background launch only the temp record runs; the
   checks of a return run at the child's end (its SubagentStop), and hooks/lib/dispatch_temp.py
   gives no background child a foreground dispatch's temp directory.
6. The Stop gate's "running" ends: past the subagent time limit only a child whose own transcript still
   grows runs, and only up to a bound; then it is lost and the block names it.
8. /dev-overnight: inside the open window a running child is waited on as outside it; with none running the
   time-lock blocks (naming a lost one); after the window the run's own wake still blocks.
Every run uses throwaway home, state and temp directories.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HOOKS))

from hooks.tests.test_stop_command_gate import dev_span, env, run, FAMILY, REAL_OVERNIGHT, overnight_fake, overnight_session  # noqa: E402,F401  (the env fixture)
from tests import cli_shapes  # noqa: E402
from tests.cli_shapes import synthesize  # noqa: E402

SID = "bg-dispatch-sid"


def _env(tmp_path, **extra):
    for sub in ("home", "state", "tmp", "project"):
        (tmp_path / sub).mkdir(exist_ok=True)
    keep = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE") and k not in ("HOME", "TMPDIR")}
    return {**keep, "HOME": str(tmp_path / "home"), "CLAUDE_STATE_DIR": str(tmp_path / "state"),
            "TMPDIR": str(tmp_path / "tmp"), "CLAUDE_PROJECT_DIR": str(tmp_path / "project"),
            "PYTHONDONTWRITEBYTECODE": "1", **extra}


def _hook(script, payload, env):
    return subprocess.run([sys.executable, str(HOOKS / script)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, cwd=env["CLAUDE_PROJECT_DIR"], timeout=120)


# ---------------------------------------------------------------- 1. any dispatch may run in the background
def _dispatch(role, background):
    tool_input = {"description": "d", "prompt": "p"}
    if role is not None:
        tool_input["subagent_type"] = role
    if background is not None:
        tool_input["run_in_background"] = background
    return {"session_id": SID, "hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": tool_input}


def _opener(tmp_path, command, args=""):
    """A transcript whose active span is ``command`` (typed); for /dev-overnight also its open window's record."""
    transcript = tmp_path / f"{SID}.jsonl"
    transcript.write_text(json.dumps(synthesize("user", "command", turnOrigin="human", message__content=(
        f"<command-message>{command} is running…</command-message>\n<command-name>/{command}</command-name>\n"
        f"<command-args>{args}</command-args>"))) + "\n")
    if command == "dev-overnight":
        claude = tmp_path / "project" / ".claude"
        claude.mkdir(parents=True, exist_ok=True)
        (claude / f"overnight-state-{SID}.json").write_text(json.dumps(
            {"session_id": SID, "end_time": "2999-01-01T00:00:00Z", "start_time": "2026-01-01T00:00:00Z"}))
    return transcript


ROLES = ["dev", "ba", "pm", "unregistered-role", None]  # None: no subagent_type (general-purpose)


@pytest.mark.parametrize("where", ["no command", "dev", "do", "dev-overnight"])
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("background", [True, None, False])
def test_1_every_dispatch_may_run_in_the_background_in_every_command(tmp_path, where, role, background):
    env = _env(tmp_path)
    payload = _dispatch(role, background)
    if where != "no command":
        payload["transcript_path"] = str(_opener(tmp_path, where, "2h" if where == "dev-overnight" else "x"))
    done = _hook("pretool-block-background-tasks.py", payload, env)
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("tool, tool_input", [("Bash", {"command": "true", "run_in_background": True}),
                                              ("Workflow", {"name": "w"})])
def test_1_a_background_shell_and_a_workflow_stay_refused(tmp_path, tool, tool_input):
    done = _hook("pretool-block-background-tasks.py", {"session_id": SID, "hook_event_name": "PreToolUse",
                                                       "tool_name": tool, "tool_input": tool_input}, _env(tmp_path))
    assert done.returncode == 2 and "[BLOCK]" in done.stderr


# ---------------------------------------------------------------- 2. a background launch resets no limit
@pytest.mark.parametrize("background, count", [(True, 4), (None, 4), (False, 0)])
def test_2_a_background_launch_keeps_the_bash_streak(tmp_path, background, count):
    env = _env(tmp_path)
    streak = tmp_path / "state" / f"claude-tool-streak-{SID}.json"
    streak.write_text(json.dumps({"schema_version": 2, "per_tool_counts": {"Edit": 1},
                                  "bash_consecutive": {"last_tool": "Bash", "count": 4}}))
    done = _hook("pretool-orchestrator-gate.py", {**_dispatch("dev", background), "tool_use_id": "toolu_1"}, env)
    assert done.returncode == 0, done.stderr
    assert json.loads(streak.read_text())["bash_consecutive"]["count"] == count


# ---------------------------------------------------------------- 3. a wake is not the owner's turn
NOTE = cli_shapes.notification("a1b2c3", "toolu_0001", "completed", result="lane done")


@pytest.mark.parametrize("prompt, kept", [(NOTE, True), ("go on", False)])
def test_3_a_notification_wake_resets_no_limit_and_keeps_the_consent(tmp_path, prompt, kept):
    env = _env(tmp_path)
    streak = tmp_path / "state" / f"claude-tool-streak-{SID}.json"
    flag = tmp_path / "state" / f"claude-orchestrator-consent-{SID}.flag"
    streak.write_text(json.dumps({"schema_version": 2, "per_tool_counts": {},
                                  "bash_consecutive": {"last_tool": "Bash", "count": 3}}))
    flag.write_text("true")
    done = _hook("prompt-workflow.py", {"session_id": SID, "hook_event_name": "UserPromptSubmit", "prompt": prompt,
                                        "cwd": env["CLAUDE_PROJECT_DIR"]}, env)
    assert done.returncode == 0, done.stderr
    assert streak.exists() is kept and flag.exists() is kept


# ---------------------------------------------------------------- 4. the Stop gate waits on a running child
def _launch(env, role="dev", age=1.0):
    """A background dev dispatch whose launch result the CLI recorded (async_launched), ``age`` minutes ago."""
    env.tx.clock = datetime.now(timezone.utc) - timedelta(minutes=age)
    env.tx.n += 1
    ident = f"toolu_{env.tx.n:04d}"
    env.tx.add(synthesize("assistant", "tool_use", message__content=[{"type": "tool_use", "id": ident, "name": "Agent",
                          "input": {"subagent_type": role, "description": role, "prompt": "work",
                                    "run_in_background": True}}]))
    env.tx.add(synthesize("user", "agent_launched", toolUseResult__agentId="agentbg1", message__content=[
        {"type": "tool_result", "tool_use_id": ident, "content": "Async agent launched successfully"}]))
    env.tx.say("running in the background; I will wait")
    return ident


def _notify(env, ident, status):
    env.tx.add(synthesize("user", "task_notification", message__content=cli_shapes.notification(
        "agentbg1", ident, status, result="lane done")))


def test_4_a_stop_while_a_child_runs_passes_as_a_wait_naming_it(env):
    dev_span(env, done=3)
    _launch(env)
    for active in (False, True):
        code, text = run(env, stop_hook_active=active)
        assert code == 0, text
        assert text.startswith("COMMAND_GATE /dev: waiting for agentbg1, still running; not complete\n")
        assert "- todo: not completed:" in text


@pytest.mark.parametrize("status", ["completed", "failed", "stopped"])
def test_4_a_child_that_ended_failed_or_was_stopped_is_not_waited_on(env, status):
    dev_span(env, done=3)
    _notify(env, _launch(env), status)
    code, text = run(env)
    assert code == 2 and text.startswith("COMMAND_GATE /dev: not complete\n"), text


def test_4_no_child_launched_blocks_as_before(env):
    dev_span(env, done=3)
    code, text = run(env)
    assert code == 2 and "waiting for" not in text


def test_4_the_waiting_state_is_read_from_the_cli_record_not_from_text(env):
    """A launch whose result the CLI did not record as async_launched (an agent's own words) is no child."""
    dev_span(env, done=3)
    env.tx.tool("Agent", {"subagent_type": "dev", "description": "dev", "prompt": "work", "run_in_background": True},
                result="Async agent launched successfully; status async_launched")
    code, _text = run(env)
    assert code == 2


# ---------------------------------------------------------------- 6. "running" ends where the harness sees it
LOST = "- background dispatch agentbg1 lost: its end never came back and it shows no life past its time limit"


def _grown(env, minutes_ago):
    """The child's own transcript, last written ``minutes_ago`` (the CLI's file beside the session's)."""
    child = env.tx.path.with_suffix("") / "subagents" / "agent-agentbg1.jsonl"
    child.parent.mkdir(parents=True, exist_ok=True)
    child.write_text("{}\n")
    at = datetime.now(timezone.utc).timestamp() - minutes_ago * 60
    os.utime(child, (at, at))


@pytest.fixture
def limit(monkeypatch):
    monkeypatch.delenv("CLAUDE_SUBAGENT_TIME_LIMIT_MINUTES", raising=False)  # 55 minutes


def test_6_a_child_past_its_limit_whose_record_keeps_growing_is_waited_on(env, limit):
    dev_span(env, done=3)
    _launch(env, age=60)  # limit 55, bound 65
    _grown(env, 1)
    code, text = run(env)
    assert code == 0 and text.startswith("COMMAND_GATE /dev: waiting for agentbg1, still running"), text


@pytest.mark.parametrize("age, grown", [(60, 20), (70, 30), (70, 0.1), (24 * 60, None)])
def test_6_a_child_silent_past_its_bound_is_lost_and_the_gate_blocks_naming_it(env, limit, age, grown):
    """Silent since before the limit, silent past the bound, or still writing past the bound (nothing the
    agent writes stretches it): not running; the block names the child as lost."""
    dev_span(env, done=3)
    _launch(env, age=age)
    if grown is not None:
        _grown(env, grown)
    code, text = run(env)
    assert code == 2 and text.startswith("COMMAND_GATE /dev: not complete\n"), text
    assert LOST in text and "dispatch that lane again" in text


def test_6_a_message_to_the_child_moves_its_dispatch_time(env, limit):
    dev_span(env, done=3)
    _launch(env, age=120)
    env.tx.clock = datetime.now(timezone.utc) - timedelta(minutes=10)
    env.tx.tool("SendMessage", {"to": "agentbg1", "message": "one more thing"})
    code, text = run(env)
    assert code == 0 and "waiting for agentbg1" in text, text


def test_6_a_child_that_ended_normally_is_neither_waited_on_nor_lost(env, limit):
    dev_span(env, done=3)
    _notify(env, _launch(env, age=24 * 60), "completed")
    code, text = run(env)
    assert code == 2 and text.startswith("COMMAND_GATE /dev: not complete\n") and "lost" not in text, text


# ---------------------------------------------------------------- 5. the return's checks run at the child's end
def _record():
    spec = importlib.util.spec_from_file_location("dispatch_record_under_test", HOOKS / "posttool-dispatch-record.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_5_at_the_launch_only_the_temp_record_runs():
    record = _record()
    rules, _raw = record.rules_for(json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Agent",
                                               "tool_response": {"status": "async_launched"}}).encode())
    assert [r.name for r in rules] == ["dispatch-temp"]
    rules, _raw = record.rules_for(json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Agent",
                                               "tool_response": {"status": "completed"}}).encode())
    assert len(rules) == 5


def test_5_at_the_childs_end_the_return_runs_with_its_launch(env):
    record = _record()
    ident = _launch(env)
    stop = {"session_id": SID, "transcript_path": str(env.tx.path), "hook_event_name": "SubagentStop",
            "agent_id": "agentbg1", "last_assistant_message": "lane done", "cwd": str(env.project)}
    rules, raw = record.rules_for(json.dumps(stop).encode())
    assert [r.name for r in rules] == [r.name for r in record.AT_RETURN]
    ret = json.loads(raw)
    assert (ret["hook_event_name"], ret["tool_use_id"], ret["tool_input"]["subagent_type"]) == ("PostToolUse", ident, "dev")
    assert ret["tool_response"]["content"][0]["text"] == "lane done" and "agent_id" not in ret
    rules, _raw = record.rules_for(json.dumps({**stop, "agent_id": "someoneelse"}).encode())
    assert rules == []
    gate = (HOOKS / "subagentstop-producer-gate.py").read_text()
    assert 'Rule("dispatch-end", str(HOOKS / "posttool-dispatch-record.py"), WITNESS)' in gate


def test_5_a_background_child_gets_no_foreground_dispatch_directory(tmp_path, monkeypatch):
    from lib import dispatch_temp
    root = tmp_path / "scratch" / SID
    root.mkdir(parents=True)
    monkeypatch.setattr(dispatch_temp, "_session_root", lambda payload: str(root))
    fg = {"tool_use_id": "fg1", "tool_input": {"run_in_background": False}}
    dispatch_temp.opened(fg)
    current = (root / ".dispatch-tmp").read_text().splitlines()[0]
    assert current and Path(current).is_dir()
    # a background launch in the same message: line 1 names no directory from now on, the open one is held
    dispatch_temp.returned({"tool_use_id": "bg1", "tool_response": {"status": "async_launched"}})
    assert (root / ".dispatch-tmp").read_text().splitlines()[0] == ""
    (Path(current) / "child-file").write_text("x")
    dispatch_temp.returned({"tool_use_id": "fg1", "tool_response": {"status": "completed"}})
    assert (Path(current) / "child-file").is_file(), "removed under the running background child"
    dispatch_temp.opened({"tool_use_id": "fg2", "tool_input": {"run_in_background": False}})
    assert (root / ".dispatch-tmp").read_text().splitlines()[0] == "", "a foreground dispatch opened a directory"
    dispatch_temp.returned({"tool_use_id": "fg2", "tool_response": {"status": "completed"}})
    dispatch_temp.returned({"tool_use_id": "bg1", "tool_response": {"status": "completed"}})  # its end
    assert not Path(current).exists() and not (root / ".dispatch-tmp").exists()


# ---------------------------------------------------------------- 7. a return's checks at a background child's end (lane bgall)
# The list (item 2 of the owner's wider decision): what runs when a dispatch returns, and where a background child gets it.
#   posttool-dispatch-record.py RULES (contract writer, overnight file check, overnight trace, dev-loop advice,
#   dispatch-temp) and the score log's sweep (posttool-close-rating.py at a return): AT_RETURN at the child's end;
#   readers of "has it returned" (lib/agent_returns, the Stop gate's background_children): the CLI's notification.
def _stop(env, agent="agentbg1"):
    return {"session_id": SID, "transcript_path": str(env.tx.path), "hook_event_name": "SubagentStop",
            "agent_id": agent, "last_assistant_message": "lane done", "cwd": str(env.project)}


@pytest.mark.parametrize("where", ["dev", "dev-overnight"])
@pytest.mark.parametrize("role", ["ba", "pm", "unregistered-role"])
def test_7_every_rule_of_a_return_runs_at_the_childs_end_with_its_return(env, monkeypatch, where, role):
    from lib import gate_runner
    if where == "dev":
        dev_span(env, done=3)
    else:
        overnight_session(env)
    record = _record()
    ident = _launch(env, role)
    rules, raw = record.rules_for(json.dumps(_stop(env)).encode())
    seen = []
    monkeypatch.setattr(gate_runner, "run_rule", lambda rule, data: seen.append((rule.name, json.loads(data)))
                        or gate_runner.Outcome(rule))
    gate_runner.evaluate(rules, raw)
    assert [name for name, _ in seen] == [r.name for r in record.RULES] + ["score-events"]
    for _name, ret in seen:
        assert (ret["hook_event_name"], ret["tool_name"], ret["tool_use_id"], ret["session_id"]) == (
            "PostToolUse", "Agent", ident, SID)
        assert ret["tool_input"]["subagent_type"] == role and "agent_id" not in ret
        assert ret["tool_response"]["status"] == "completed"


def test_7_the_score_sweep_runs_at_the_childs_end(env, monkeypatch):
    """The score log's sweep (lib/score_events.observe) runs on the return built at the child's end."""
    from lib import score_events
    dev_span(env, done=3)
    record = _record()
    _launch(env, "architect")
    swept = []
    monkeypatch.setattr(score_events, "sweep", lambda tp, cwd: swept.append((tp, cwd)))
    rules, raw = record.rules_for(json.dumps(_stop(env)).encode())
    record.evaluate(rules, raw)
    assert swept == [(str(env.tx.path), str(env.project))]


@pytest.mark.parametrize("role", ["ba", "unregistered-role"])
def test_7_has_it_returned_is_read_at_the_childs_notification_for_any_role(env, role):
    from lib import agent_returns, command_span
    overnight_session(env)
    ident = _launch(env, role)
    span = command_span.active_span(str(env.tx.path))
    call = next(c for c in span.dispatch_calls() if c.id == ident)
    assert agent_returns.Returns(span).line(call) == 0
    _notify(env, ident, "completed")
    span = command_span.active_span(str(env.tx.path))
    call = next(c for c in span.dispatch_calls() if c.id == ident)
    assert agent_returns.Returns(span).line(call) > 0


# ---------------------------------------------------------------- 8. /dev-overnight: the wait and the time-lock
def _window(end, open_):
    fake = overnight_fake({"session_id": SID, "end_time": end}, window=open_)
    fake.parse_end_time = REAL_OVERNIGHT.parse_end_time
    return fake


def test_8_inside_the_overnight_window_a_running_child_is_waited_on(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "lib.overnight", _window("2999-01-01T00:00:00Z", True))
    overnight_session(env)
    _launch(env, "pm")
    code, text = run(env)
    assert code == 0 and "waiting for agentbg1" in text, text


WAIT = "COMMAND_GATE /dev-overnight: waiting for agentbg1, still running; not complete\n"


@pytest.mark.parametrize("active", [False, True])
def test_8_inside_the_window_the_wait_says_what_it_says_outside_and_is_shown_to_the_owner(env, monkeypatch, limit,
                                                                                         active, capsys):
    """Item 1: the window open (end_time ahead), a child launched 5 minutes ago (limit 55): the stop is the
    wait, with the line of the wait outside the window, as systemMessage; no time-lock text."""
    monkeypatch.setitem(sys.modules, "lib.overnight", _window("2999-01-01T00:00:00Z", True))
    overnight_session(env)
    _launch(env, "pm", age=5)
    code, text = run(env, stop_hook_active=active)
    assert (code, text) == (0, WAIT), text
    from hooks.tests.test_stop_command_gate import gate
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({**env.payload, "stop_hook_active": active})))
    assert gate.main([]) == 0
    assert json.loads(capsys.readouterr().out) == {"systemMessage": WAIT}


@pytest.mark.parametrize("child", ["none launched", "completed"])
def test_8_inside_the_overnight_window_with_no_child_running_the_time_lock_blocks(env, monkeypatch, child):
    """Item 2: no child runs and the window is open: the time-lock's text exactly, nothing about children."""
    monkeypatch.setitem(sys.modules, "lib.overnight", _window("2999-01-01T00:00:00Z", True))
    overnight_session(env)
    if child == "completed":
        _notify(env, _launch(env, "pm"), "completed")
    code, text = run(env)
    assert code == 2 and text.startswith("COMMAND_GATE time-lock: overnight window open until 2999-01-01T00:00:00Z, "), text
    assert text.endswith("left; continue the remaining pipelines\n") and text.count("\n") == 1, text


@pytest.mark.parametrize("age, grown", [(60, 20), (24 * 60, None)])
def test_8_inside_the_window_a_lost_child_blocks_and_is_named(env, monkeypatch, limit, age, grown):
    """Item 3: a child past its bound (launched 60 min ago and silent 20 min; a day ago with no transcript) is
    not waited on inside the window either: the time-lock blocks and names it with the lost line."""
    monkeypatch.setitem(sys.modules, "lib.overnight", _window("2999-01-01T00:00:00Z", True))
    overnight_session(env)
    _launch(env, "pm", age=age)
    if grown is not None:
        _grown(env, grown)
    code, text = run(env)
    assert code == 2 and text.startswith("COMMAND_GATE time-lock: overnight window open"), text
    assert LOST in text and "dispatch that lane again" in text and "waiting for" not in text, text


def test_8_inside_the_window_a_child_past_its_limit_still_growing_is_waited_on(env, monkeypatch, limit):
    """Item 1 with the bound: launched 60 min ago (limit 55, bound 65), its transcript grew 1 min ago."""
    monkeypatch.setitem(sys.modules, "lib.overnight", _window("2999-01-01T00:00:00Z", True))
    overnight_session(env)
    _launch(env, "pm", age=60)
    _grown(env, 1)
    assert run(env) == (0, WAIT)


def test_8_after_the_window_the_runs_own_wake_still_blocks_with_a_child_running(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "lib.overnight", _window("2000-01-01T00:00:00Z", False))
    overnight_session(env, wake=True)
    _launch(env, "pm")
    code, text = run(env)
    assert code == 2 and "CronCreate job cron-7" in text, text
