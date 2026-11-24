"""Returns held (hooks/lib/returns_hold.py, a rule of hooks/userprompt-launch.py): the background returns of one
orchestrator come back as one batch. Notices are the CLI's recorded shapes (tests/cli_shapes; the deadline notice
as CLI 2.1.322 wrote an asyncRewake UserPromptSubmit hook's exit 2), with neutral values. Throwaway state."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HOOKS))

from hooks.tests.test_stop_command_gate import dev_span, env, SID  # noqa: E402,F401  (the env fixture)
from tests import cli_shapes  # noqa: E402
from tests.cli_shapes import synthesize  # noqa: E402
from lib import returns_hold as hold  # noqa: E402

FINAL = ("A task-notification fires each time this agent stops with no live background children of its own. "
         "The user can send it another message and resume it, so the same task-id may notify more than once.")
A, B = "a0000000000000001", "a0000000000000002"


@pytest.fixture(autouse=True)
def switched_on(monkeypatch):
    """The hold ships off; every test but the off ones below runs it switched on."""
    monkeypatch.setenv(hold.SETTING, "on")


def _launch(env, agent):
    env.tx.clock = datetime.now(timezone.utc)
    env.tx.n += 1
    ident = f"toolu_{env.tx.n:04d}"
    env.tx.add(synthesize("assistant", "tool_use", message__content=[{"type": "tool_use", "id": ident, "name": "Agent",
                          "input": {"subagent_type": "dev", "description": "dev", "prompt": "work",
                                    "run_in_background": True}}]))
    env.tx.add(synthesize("user", "agent_launched", toolUseResult__agentId=agent, message__content=[
        {"type": "tool_result", "tool_use_id": ident, "content": "Async agent launched successfully"}]))
    return ident


def _notice(agent, ident, status="completed", note=FINAL):
    text = cli_shapes.notification(agent, ident, status, result=f"lane {agent} done")
    text = text.replace("<TMP>/claude-<UID>/<CWD_SLUG>/<UUID>/tasks/<AGENT_ID>.output", f"/scratch/tasks/{agent}.output")
    text = text.replace("<summary><redacted></summary>", f'<summary>Agent "lane" finished</summary>')
    text = text.replace("<note><redacted></note>", f"<note>{note}</note>")
    return text.replace("<usage><redacted></usage>", "<usage><subagent_tokens>10</subagent_tokens><tool_uses>2"
                                                      "</tool_uses><duration_ms>300</duration_ms></usage>")


def _arrive(env, text, idle=True):
    """The CLI queues the notice; an idle session takes it off the queue for its own turn before the hooks run."""
    env.tx.add(synthesize("queue-operation", "enqueue", content=text))
    if idle:
        env.tx.add(synthesize("queue-operation", "dequeue"))
    return {"session_id": SID, "transcript_path": str(env.tx.path), "cwd": str(env.project),
            "hook_event_name": "UserPromptSubmit", "prompt": text, "prompt_id": "p"}


def _batch(env):
    dev_span(env, done=3)
    return _launch(env, A), _launch(env, B)


DEADLINE = ("<task-notification>\n<summary>Stop hook feedback</summary>\n</task-notification>\n<system-reminder>\n"
            "Stop hook blocking error from command \"UserPromptSubmit\": " + hold.DEADLINE_MARK +
            ": the deadline of the held background returns passed (1 held since 2026-01-01T00:00:00Z); they are "
            "handed over with this notice.\n\n</system-reminder>")


def test_two_siblings_the_first_return_is_held_and_the_second_delivers_both(env):
    ia, ib = _batch(env)
    first = hold.decide(_arrive(env, _notice(A, ia)))
    assert first["decision"] == "block" and A in first["reason"]
    second = hold.decide(_arrive(env, _notice(B, ib)))
    context = second["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("HELD RETURNS (1)") and f"<task-id>{A}</task-id>" in context and f"lane {A} done" in context
    assert "Still running" not in context
    assert hold.decide(_arrive(env, "next typed prompt")) is None  # the batch is gone with its hand-over


def test_the_deadline_passes_with_a_sibling_silent_everything_is_delivered_naming_it(env):
    ia, _ib = _batch(env)
    assert hold.decide(_arrive(env, _notice(A, ia)))["decision"] == "block"
    later = time.time() + hold.WINDOW + 10
    out = hold.decide(_arrive(env, DEADLINE), now=later)
    context = out["hookSpecificOutput"]["additionalContext"]
    assert f"<task-id>{A}</task-id>" in context
    assert context.rstrip().endswith(f"The batch's deadline passed; still silent: {B}.")


def test_the_waker_fires_once_for_the_batch_it_was_armed_for(env):
    ia, _ib = _batch(env)
    payload = _arrive(env, _notice(A, ia))
    start = time.time()
    clock = iter([start, start + hold.WINDOW + 6])
    assert hold.decide(payload, now=start)["decision"] == "block"
    code, text = hold.deadline(payload, sleep=lambda s: None, clock=lambda: next(clock))
    assert code == 2 and text.startswith(hold.DEADLINE_MARK)
    late = [start + 600, start + 600 + hold.WINDOW + 6]  # a sibling's waker, armed after the batch opened
    assert hold.deadline(payload, sleep=lambda s: None, clock=iter(late).__next__)[0] == 2  # the first one never woke
    hold.decide(_arrive(env, DEADLINE), now=start + hold.WINDOW + 7)  # the first one's notice handed the batch over
    assert hold.deadline(payload, sleep=lambda s: None, clock=iter(late).__next__) == (0, "")


def test_the_deadline_notice_is_not_held_and_a_return_past_the_deadline_is_not_held(env):
    ia, ib = _batch(env)
    assert hold.decide(_arrive(env, DEADLINE)) is None  # nothing held, nothing to say
    assert hold.decide(_arrive(env, _notice(A, ia)))["decision"] == "block"
    out = hold.decide(_arrive(env, _notice(B, ib)), now=time.time() + hold.WINDOW + 1)
    assert "decision" not in out and f"<task-id>{A}</task-id>" in out["hookSpecificOutput"]["additionalContext"]


def test_the_owners_typed_message_is_not_held_and_delivers_what_is_held(env):
    ia, _ib = _batch(env)
    assert hold.decide(_arrive(env, _notice(A, ia)))["decision"] == "block"
    out = hold.decide(_arrive(env, "how far are the lanes?"))
    assert "decision" not in out
    context = out["hookSpecificOutput"]["additionalContext"]
    assert f"<task-id>{A}</task-id>" in context and f"Still running: {B}." in context


@pytest.mark.parametrize("shape", ["failed", "interim", "shell-task", "two-in-one", "extra-text", "mid-turn"])
def test_a_notice_of_another_shape_or_drained_mid_turn_is_delivered(env, shape):
    ia, _ib = _batch(env)
    text = {"failed": _notice(A, ia, "failed"),
            "interim": _notice(A, ia, note="This agent stopped with background work of its own still running."),
            "shell-task": _notice("b0000001", ia),
            "two-in-one": _notice(A, ia) + "\n" + _notice(A, ia),
            "extra-text": _notice(A, ia) + "\nplease look",
            "mid-turn": _notice(A, ia)}[shape]
    assert hold.decide(_arrive(env, text, idle=shape != "mid-turn")) is None


def test_no_sibling_running_or_no_span_holds_nothing(env):
    dev_span(env, done=3)
    ia = _launch(env, A)
    assert hold.decide(_arrive(env, _notice(A, ia))) is None


def test_unreadable_state_delivers(env):
    ia, _ib = _batch(env)
    path = Path(hold._path(SID))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json")
    assert hold.decide(_arrive(env, _notice(A, ia))) is None


@pytest.mark.parametrize("value", [None, "off", "", "1", "ON"])
def test_off_unless_switched_on_nothing_is_held_written_or_woken(env, monkeypatch, value):
    ia, ib = _batch(env)
    if value is None:
        monkeypatch.delenv(hold.SETTING)
    else:
        monkeypatch.setenv(hold.SETTING, value)
    payload = _arrive(env, _notice(A, ia))
    assert hold.decide(payload) is None
    assert hold.decide(_arrive(env, _notice(B, ib))) is None
    assert not Path(hold._path(SID)).parent.exists()  # no state, no lock
    assert hold.deadline(payload, sleep=lambda s: pytest.fail("the waker slept")) == (0, "")
    waker = subprocess.run(["bash", str(HOOKS / hold.WAKER)], input=json.dumps(payload), capture_output=True,
                           text=True, env=dict(os.environ), timeout=30)
    assert (waker.returncode, waker.stdout, waker.stderr) == (0, "", "")
    launcher = subprocess.run([sys.executable, str(HOOKS / "userprompt-launch.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=dict(os.environ), timeout=120)
    assert launcher.returncode == 0 and "returns-hold" not in launcher.stderr


def test_switched_off_after_a_hold_what_was_held_is_still_handed_over(env, monkeypatch):
    ia, _ib = _batch(env)
    assert hold.decide(_arrive(env, _notice(A, ia)))["decision"] == "block"
    monkeypatch.delenv(hold.SETTING)
    out = hold.decide(_arrive(env, "go on"))
    assert f"<task-id>{A}</task-id>" in out["hookSpecificOutput"]["additionalContext"]
    assert not Path(hold._path(SID)).exists()


def test_the_waker_reads_settings_through_the_one_load(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [
        {"command": "bash x/" + hold.WAKER, "asyncRewake": True, "timeout": 1920}]}]}}))
    assert hold.waker_registered(str(settings))
    settings.write_text(json.dumps({"hooks": {"UserPromptSubmit": {"not": "a list"}}}))
    assert not hold.waker_registered(str(settings))  # load_settings' verdict: unusable
    assert not hold.waker_registered(str(tmp_path / "absent.json"))


def test_without_the_waker_registered_nothing_is_held(env, monkeypatch, tmp_path):
    ia, _ib = _batch(env)
    settings = tmp_path / "settings.json"  # registered, but not in the background: no deadline can come of it
    settings.write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [{"command": "bash x/" + hold.WAKER,
                                                                                 "timeout": 1920}]}]}}))
    assert not hold.waker_registered(str(settings))
    monkeypatch.setattr(hold, "waker_registered", lambda settings_path=None: False)
    assert hold.decide(_arrive(env, _notice(A, ia))) is None


def test_the_tree_registers_the_waker_and_the_launcher_holds_through_its_rule(env):
    ia, _ib = _batch(env)
    assert hold.waker_registered()
    proc = subprocess.run([sys.executable, str(HOOKS / "userprompt-launch.py")], input=json.dumps(
        _arrive(env, _notice(A, ia))), capture_output=True, text=True, env=dict(os.environ), timeout=120)
    assert proc.returncode == 2 and f"returns-hold: held the return of {A}" in proc.stderr


def _passes(env, text, answer):
    """What the CLI records for a notice that passes: its own turn, then the hooks' JSON context."""
    env.tx.add(synthesize("user", "task_notification", message__content=text))
    context = ((answer or {}).get("hookSpecificOutput") or {}).get("additionalContext")
    if context:  # the launcher joins the rules' contexts, this rule's last
        env.tx.add(synthesize("attachment/hook_additional_context", attachment__content=[f"other rule\n{context}"]))


def test_in_a_gated_command_a_handed_over_return_has_returned_for_the_stop_gate(env):
    ia, ib = _batch(env)
    gate = hold._gate()
    assert hold.decide(_arrive(env, _notice(A, ia)))["decision"] == "block"  # the CLI records no delivery of it
    span = gate.command_span.active_span(str(env.tx.path))
    assert span.command in gate.command_span.GATED_COMMANDS and gate.children(span) == ([A, B], [])
    text = _notice(B, ib)
    _passes(env, text, hold.decide(_arrive(env, text)))
    span = gate.command_span.active_span(str(env.tx.path))
    assert {e.agent for e in span.agent_ends()} == {A, B}
    assert gate.children(span) == ([], [])
    assert gate.background_children(span, now=time.time() + 24 * 3600) == ([], [])  # never lost past its bound


def test_a_hold_is_recorded_with_its_seconds_and_is_no_refusal_for_the_reader(env, tmp_path):
    from lib import refusal_record as R
    ia, ib = _batch(env)
    proc = subprocess.run([sys.executable, str(HOOKS / "userprompt-launch.py")], input=json.dumps(
        _arrive(env, _notice(A, ia))), capture_output=True, text=True, env=dict(os.environ), timeout=120)
    assert proc.returncode == 2  # the launcher held it and wrote its refusal line
    hold.decide(_arrive(env, _notice(B, ib)), now=time.time() + 42)
    lines = [json.loads(x) for f in Path(R.directory()).glob("refusals-*.jsonl") for x in f.read_text().splitlines()]
    assert [x["kind"] for x in lines] == [R.HELD]
    reader = [sys.executable, str(ROOT / "scripts" / "refusals")]
    run = dict(capture_output=True, text=True, env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]}, timeout=120)
    s = json.loads(subprocess.run(reader + ["--json"], **run).stdout)
    assert (s["refusals"], s["held"], s["by_event"]) == (0, 1, [])
    (one,) = s["held_returns"]
    assert one["agent"] == A and 41 <= one["seconds"] <= 60
    assert "background returns held, then handed over (not refusals): 1" in subprocess.run(reader, **run).stdout
    (tmp_path / "rows").write_text("")
    done = subprocess.run(reader + ["reconcile", "--refusals", str(tmp_path / "rows")], **run)
    assert done.returncode == 0 and "'no transcript line': 0" in done.stdout
