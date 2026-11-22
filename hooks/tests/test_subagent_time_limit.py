"""The time limit of a dispatched subagent (hooks/pretool-subagent-time-limit.py).

The clock is set by each test: the subagent's own transcript, as the CLI keeps it beside the
session's (<session>/subagents/agent-<id>.jsonl), is written with record timestamps that many
minutes before now. Throwaway HOME, state and project directories; neutral values.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-subagent-time-limit.py"
SID, AGENT = "sess-0001", "a0123456789abcdef"


def _ago(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


@pytest.fixture
def box(tmp_path):
    proj, home, state = tmp_path / "proj", tmp_path / "home", tmp_path / "state"
    for d in (proj, home, state):
        d.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "CODEX_"))}
    env.update(HOME=str(home), CLAUDE_STATE_DIR=str(state), CLAUDE_SESSION_ID=SID,
               CLAUDE_PROJECT_DIR=str(proj), PYTHONDONTWRITEBYTECODE="1")
    session = tmp_path / f"{SID}.jsonl"
    session.write_text("")
    (tmp_path / SID / "subagents").mkdir(parents=True)
    return {"tmp": tmp_path, "proj": proj, "env": env, "session": session, "state": state, "home": home,
            "agent": tmp_path / SID / "subagents" / f"agent-{AGENT}.jsonl"}


def dispatched(box, minutes, prompt="Do the one issue. Report: docs/lane-report.md", sends=()):
    """The subagent's transcript: dispatched ``minutes`` ago, then each (minutes ago, kind, text) send."""
    rows = [{"type": "user", "agentId": AGENT, "timestamp": _ago(minutes),
             "message": {"role": "user", "content": prompt}},
            {"type": "assistant", "timestamp": _ago(minutes - 1),
             "message": {"content": [{"type": "text", "text": 'quoting "origin":{"kind":"coordinator"} as text'}]}}]
    for ago, kind, text in sends:
        if kind == "resume":
            rows.append({"type": "user", "timestamp": _ago(ago), "origin": {"kind": "coordinator"},
                         "message": {"role": "user", "content": text}})
        else:
            rows.append({"type": "attachment", "timestamp": _ago(ago), "attachment": {
                "type": "queued_command", "prompt": text, "origin": {"kind": "coordinator"}}})
    box["agent"].write_text("".join(json.dumps(r) + "\n" for r in rows))


def call(box, tool="Bash", tool_input=None, agent=AGENT, env=None, hook=HOOK):
    payload = {"hook_event_name": "PreToolUse", "session_id": SID, "tool_name": tool,
               "tool_input": tool_input if tool_input is not None else {"command": "echo neutral"},
               "tool_use_id": "toolu_x1", "cwd": str(box["proj"]), "transcript_path": str(box["session"])}
    if agent:
        payload.update(agent_id=agent, agent_type="general-purpose")
    return subprocess.run([sys.executable, str(hook)], input=json.dumps(payload), capture_output=True,
                          text=True, env={**box["env"], **(env or {})}, timeout=60)


def _notice(p):
    return json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"] if p.stdout.strip() else ""


def test_before_fifty_minutes_nothing(box):
    dispatched(box, 44)  # the notice starts 10 minutes (the Bash ceiling) before the limit
    p = call(box)
    assert (p.returncode, p.stdout, p.stderr) == (0, "", "")


def _bash(timeout=None, background=None):
    ask = {"command": "echo neutral"}
    ask.update({k: v for k, v in (("timeout", timeout), ("run_in_background", background)) if v is not None})
    return ask


def test_after_the_notice_a_command_that_would_outrun_the_limit_is_refused(box):
    dispatched(box, 46)
    p = call(box, "Bash", _bash(600000))
    assert p.returncode == 2 and "REFUSED" in p.stderr and "only 9.0 min are left" in p.stderr
    assert "shorter timeout" in p.stderr and "write your report" in p.stderr
    p = call(box, "Bash", _bash(120000))
    assert p.returncode == 0 and "[subagent time limit]" in _notice(p)


def test_a_command_with_no_timeout_is_judged_by_the_tool_s_default(box):
    dispatched(box, 52)
    assert call(box, "Bash", _bash()).returncode == 0  # 2 min default, 3 left
    dispatched(box, 54)
    p = call(box, "Bash", _bash())
    assert p.returncode == 2 and "may run 2 min" in p.stderr
    assert call(box, "Bash", _bash(), env={"BASH_DEFAULT_TIMEOUT_MS": "30000"}).returncode == 0
    assert call(box, "Bash", _bash(30000)).returncode == 0
    assert call(box, "Bash", _bash(background=True)).returncode == 0  # not waited for: named in the ledger row


def test_before_the_notice_every_command_passes(box):
    dispatched(box, 44)
    for ask in (_bash(600000), _bash(), _bash(7200000, True)):
        p = call(box, "Bash", ask)
        assert (p.returncode, p.stdout, p.stderr) == (0, "", "")


def test_an_obeying_child_s_commands_all_end_by_the_limit(box):
    """Every foreground Bash call the rule lets through ends by minute 55, wherever it starts."""
    for start in [x * 2.5 for x in range(23)]:
        dispatched(box, start)
        for timeout in (None, 60000, 120000, 600000, 900000):
            if call(box, "Bash", _bash(timeout)).returncode == 0:
                assert start + min((timeout or 120000), 600000) / 60000 <= 55 + 0.1, (start, timeout)


def test_the_report_write_after_the_limit_still_passes(box):
    dispatched(box, 58)
    assert call(box, "Write", {"file_path": "docs/lane-report.md", "content": "x"}).returncode == 0
    assert call(box, "Bash", _bash(1000)).returncode == 2


def test_between_fifty_and_fifty_five_every_call_carries_the_notice(box):
    dispatched(box, 52)
    for tool, ti in (("Bash", None), ("Edit", {"file_path": str(box["proj"] / "a.py"), "old_string": "a",
                                                "new_string": "b"})):
        p = call(box, tool, ti)
        assert p.returncode == 0, p.stderr
        text = _notice(p)
        assert "[subagent time limit]" in text and "Write your report now and stop" in text
        assert "blocking_issues" in text and "first line of your final reply" in text


def test_after_fifty_five_a_work_call_is_refused(box):
    dispatched(box, 56)
    for tool, ti in (("Bash", None), ("Edit", {"file_path": str(box["proj"] / "a.py"), "old_string": "a",
                                                "new_string": "b"}),
                     ("Write", {"file_path": str(box["proj"] / "hooks" / "a.py"), "content": "x"}),
                     ("Write", {"file_path": str(box["proj"] / "docs" / "other.md"), "content": "x"}),
                     ("Read", {"file_path": str(box["proj"] / "a.py")}), ("Agent", {"prompt": "go on"})):
        p = call(box, tool, ti)
        assert p.returncode == 2, (tool, ti)
        assert "REFUSED" in p.stderr and "over the 55-minute limit" in p.stderr


def test_after_fifty_five_the_report_write_is_let_through(box):
    dispatched(box, 56)
    report = box["proj"] / "docs" / "lane-report.md"
    assert call(box, "Write", {"file_path": str(report), "content": "Stopped by the time limit."}).returncode == 0
    assert call(box, "Write", {"file_path": "docs/lane-report.md", "content": "x"}).returncode == 0  # relative to cwd
    assert call(box, "Read", {"file_path": str(report)}).returncode == 0
    assert call(box, "Edit", {"file_path": str(report), "old_string": "a", "new_string": "b"}).returncode == 2


def test_the_report_name_cannot_be_a_link_to_other_work(box):
    dispatched(box, 56)
    (box["proj"] / "docs").mkdir()
    (box["proj"] / "code.py").write_text("x = 1\n")
    (box["proj"] / "docs" / "lane-report.md").symlink_to(box["proj"] / "code.py")
    p = call(box, "Write", {"file_path": str(box["proj"] / "docs" / "lane-report.md"), "content": "y"})
    assert p.returncode == 2


def test_after_fifty_five_the_stop_is_let_through(box):
    dispatched(box, 120)
    stop = {"hook_event_name": "SubagentStop", "session_id": SID, "agent_id": AGENT,
            "transcript_path": str(box["session"]), "cwd": str(box["proj"])}
    launcher = ROOT / "hooks" / "pretool-launch.py"
    rules = subprocess.run([sys.executable, "-c", "import runpy,sys; m=runpy.run_path(sys.argv[1]); "
                            "print(sorted({t for r in m['RULES'] if r.name=='subagent-time-limit' for t in [r.tools]}, key=str))",
                            str(launcher)], capture_output=True, text=True, env=box["env"], timeout=60)
    assert rules.stdout.strip() == "[None]", rules.stderr  # a PreToolUse rule of every tool, and no other event's
    p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(stop), capture_output=True, text=True,
                       env=box["env"], timeout=60)
    assert (p.returncode, p.stdout, p.stderr) == (0, "", "")  # the stop is no tool call: nothing to refuse


@pytest.mark.parametrize("kind", ["resume", "queued"])
def test_a_message_starts_the_clock_again(box, kind):
    dispatched(box, 180, sends=[(120, kind, "first message"), (10, kind, "Go on. Report: docs/round2.md")])
    p = call(box)
    assert (p.returncode, p.stdout) == (0, ""), p.stderr
    dispatched(box, 180, sends=[(56, kind, "Go on. Report: docs/round2.md")])
    assert call(box).returncode == 2
    assert call(box, "Write", {"file_path": "docs/round2.md", "content": "x"}).returncode == 0
    assert call(box, "Write", {"file_path": "docs/lane-report.md", "content": "x"}).returncode == 0  # the first prompt's


@pytest.mark.parametrize("kind", ["resume", "queued"])
def test_the_clock_and_the_declared_message_come_from_one_reader(box, kind):
    """The record that restarts the clock is the one lib/obligation.latest_send takes the message from:
    both read obligation.latest_delivery (the first record, and the latest delivery, not a quote of one)."""
    sys.path.insert(0, str(ROOT))
    try:
        from hooks.lib import obligation
    finally:
        sys.path.pop(0)
    dispatched(box, 180, sends=[(120, kind, "first message"), (10, kind, "Go on. Report: docs/round2.md")])
    rows = [json.loads(line) for line in box["agent"].read_text().splitlines()]
    assert obligation.latest_delivery(box["agent"]) == (rows[0], rows[-1])
    assert obligation.latest_send(box["agent"]) == "Go on. Report: docs/round2.md"
    assert call(box).returncode == 0
    dispatched(box, 180)
    assert obligation.latest_delivery(box["agent"])[1] is None  # the quoted origin is no delivery
    assert obligation.latest_send(box["agent"]) is None


def test_the_limit_is_one_setting(box):
    dispatched(box, 26)
    assert "[subagent time limit]" in _notice(call(box, env={"CLAUDE_SUBAGENT_TIME_LIMIT_MINUTES": "30"}))
    dispatched(box, 31)
    p = call(box, env={"CLAUDE_SUBAGENT_TIME_LIMIT_MINUTES": "30"})
    assert p.returncode == 2 and "over the 30-minute limit" in p.stderr
    for unset in ({}, {"CLAUDE_SUBAGENT_TIME_LIMIT_MINUTES": "soon"}, {"CLAUDE_SUBAGENT_TIME_LIMIT_MINUTES": "0"}):
        assert call(box, env=unset).returncode == 0  # the default, 55
    assert call(box, env={"CLAUDE_SUBAGENT_TIME_LIMIT_MINUTES": "90"}).returncode == 0
    dispatched(box, 56)
    assert call(box, env={"CLAUDE_SUBAGENT_TIME_LIMIT_MINUTES": "90"}).returncode == 0


def test_the_main_agent_and_an_unreadable_record_are_not_limited(box):
    dispatched(box, 300)
    assert call(box, agent=None).returncode == 0
    assert call(box, agent="a-other-agent").returncode == 0  # no transcript of that agent
    box["agent"].write_text("not json\n")
    assert call(box).returncode == 0


def test_a_refusal_is_recorded_and_released_by_the_owner_s_allow(box):
    dispatched(box, 56)
    launcher = ROOT / "hooks" / "pretool-launch.py"
    refused = call(box, "TodoWrite", {"todos": []}, hook=launcher)
    assert refused.returncode == 2 and "[subagent time limit] REFUSED" in refused.stderr
    recorded = [json.loads(line) for f in box["home"].rglob("refusals-*.jsonl") for line in f.read_text().splitlines()]
    assert any("pretool-subagent-time-limit.py" in json.dumps(r) for r in recorded)
    owner = {"hook_event_name": "UserPromptSubmit", "session_id": SID, "prompt": "/allow", "cwd": str(box["proj"])}
    subprocess.run(["bash", str(ROOT / "hooks" / "userprompt-consent-allowlist.sh")], input=json.dumps(owner),
                   capture_output=True, text=True, env=box["env"], timeout=60, check=True)
    released = call(box, "TodoWrite", {"todos": []}, hook=launcher)
    assert released.returncode == 0, released.stderr
    assert "RELEASED" in json.loads(released.stdout)["systemMessage"]
    assert call(box, "TodoWrite", {"todos": []}, hook=launcher).returncode == 2  # the grant is spent
