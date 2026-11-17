#!/usr/bin/env python3
"""A subagent that reports through SubagentHandback is read by its report (T7).

In auto mode a subagent delivers its final report as a SubagentHandback call: the
report is the call's ``input.message`` in the agent's own transcript, and the
SubagentStop payload carries no ``last_assistant_message``
(fixtures/cli-subagent-handback-stop.json, recorded on Claude Code 2.1.326). The
SubagentStop rules that read the final report, G2's response_line, response_block,
waived_by_response and verdict_class checks and the /restart response tracker, read
that message as the report (hooks/lib/final_report.py); a stop with neither a
handback nor a reply is refused as before.
"""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import test_artifact_contract_enforce as base  # noqa: E402  (hooks/tests on sys.path)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOKS = REPO_ROOT / "hooks"
GATE = HOOKS / "subagentstop-producer-gate.py"
TRACK = HOOKS / "subagentstop-restart-track.py"
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "cli-subagent-handback-stop.json").read_text(encoding="utf-8"))

sys.path.insert(0, str(HOOKS))
from lib import final_report  # noqa: E402

# commands/close.md's close-QA obligation: the file's terminal line and the reply's.
CLOSE = r"^(CLOSE: YES([ \-\u2014(].*)?|CLOSE_FINDINGS: [0-9]+ items?)$"
CLOSE_REPLY = r"^(CLOSE: YES([ \-\u2014(].*)?|CLOSE_FINDINGS: [0-9]+ items?|CLOSE_REPORT_APPEND_(ERROR|CRITICAL): .*)$"
SESSION = "harness-handback"


def _handback_run(report: str, records: str = "text_then_handback_records", second: str | None = None) -> list:
    """The observed records of one run that ends in a handback, carrying ``report``."""
    tail = copy.deepcopy(FIXTURE[records])
    calls = [b for r in tail if r["type"] == "assistant" for b in r["message"]["content"] if b.get("type") == "tool_use"]
    calls[0]["input"]["message"] = report
    if second is not None:
        calls[1]["input"]["message"] = second
    return tail


def _transcript(home: Path, project: Path, agent_id: str, prompt: str, *runs: list) -> Path:
    """The agent's own transcript: its dispatch prompt, the CLI's handback reminder, then ``runs``."""
    folder = home / ".claude" / "projects" / base._project_slug(project) / SESSION / "subagents"
    folder.mkdir(parents=True, exist_ok=True)
    start = copy.deepcopy(FIXTURE["run_start_records"])
    start[0]["message"]["content"] = prompt
    records = start + [r for run in runs for r in run]
    path = folder / f"agent-{agent_id}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    (folder / f"agent-{agent_id}.meta.json").write_text(json.dumps({"toolUseId": "tooluse-test-1"}), encoding="utf-8")
    return path


def _resumed(text: str) -> list:
    """A later run: the message that resumed the agent and a plain reply."""
    return [{"type": "user", "isSidechain": True, "message": {"role": "user", "content": "Continue."}},
            {"type": "assistant", "isSidechain": True, "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}]


def _close_qa(tmp_path: Path, agent_id: str, *runs: list, **stop) -> subprocess.CompletedProcess:
    """A close QA owing a markdown close report and a response line, stopping as the CLI stops it."""
    task_id = "20260101-000701"
    md_path = f"docs/dev/close-report-{task_id}.md"
    project, home = base._standard_setup(tmp_path, "qa", agent_id)
    prompt = base._obligation_block_multi(task_id, [
        {"kind": "markdown", "path": md_path, "identity_anchor": task_id, "terminal_line_regex": CLOSE,
         "waived_by_response": "^CLOSE_REPORT_APPEND_(ERROR|CRITICAL): "},
        {"kind": "response_line", "terminal_line_regex": CLOSE_REPLY},
    ], role="qa", consistency="verdict_class")
    path = _transcript(home, project, agent_id, prompt, *runs)
    base._write(project / md_path, f"# Close Debate Report\n{task_id}\nCLOSE: YES\n")
    return _stop(project, home, agent_id, path, **stop)


def _stop(project: Path, home: Path, agent_id: str, path: Path, hook: Path = base.HOOK_PATH,
          last_assistant_message: str | None = None, payload_path: bool = False,
          agent_type: str = "qa") -> subprocess.CompletedProcess:
    """The SubagentStop payload the CLI sends, as recorded: no last_assistant_message unless given."""
    payload = dict(FIXTURE["subagent_stop_payload"])
    payload.update(session_id=SESSION, agent_id=agent_id, agent_type=agent_type, cwd=str(project),
                   transcript_path=str(home / "absent-parent.jsonl"),
                   agent_transcript_path=str(path) if payload_path else "")
    if last_assistant_message is not None:
        payload["last_assistant_message"] = last_assistant_message
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), HOME=str(home),
               CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_OBLIGATION_STOPGATE="block")
    env.pop("CLAUDE_HOME", None)
    env.pop("ARTIFACT_CONTRACT_ENFORCE_MODE", None)
    return subprocess.run([sys.executable, str(hook)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, timeout=60)


def test_the_recorded_stop_carries_the_report_only_in_the_handback_call():
    payload = FIXTURE["subagent_stop_payload"]
    assert "last_assistant_message" not in payload
    assert {"transcript_path", "agent_transcript_path", "agent_id"} <= set(payload)
    for key in ("text_then_handback_records", "two_handbacks_records"):
        records = FIXTURE[key]
        last = [r for r in records if r["type"] == "assistant"][-1]
        assert [b["name"] for b in last["message"]["content"]] == ["SubagentHandback"]
        assert not [b for b in last["message"]["content"] if b.get("type") == "text"]


def test_a_handback_report_satisfies_the_response_line(tmp_path):
    proc = _close_qa(tmp_path, "agent-qa-hb-line", _handback_run("Findings.\nCLOSE: YES"))
    assert proc.returncode == 0, proc.stderr


def test_a_handback_report_is_judged_like_a_reply(tmp_path):
    proc = _close_qa(tmp_path, "agent-qa-hb-wrong", _handback_run("Findings.\nNOT-A-LEGAL-VERDICT-LINE"))
    assert proc.returncode == 2
    assert "<response_line>" in proc.stderr and "terminal_line_mismatch" in proc.stderr


def test_the_handback_report_is_read_through_the_payload_path_too(tmp_path):
    proc = _close_qa(tmp_path, "agent-qa-hb-l0", _handback_run("CLOSE: YES"), payload_path=True)
    assert proc.returncode == 0, proc.stderr


def test_a_handback_report_feeds_the_waiver_and_the_verdict_class(tmp_path):
    waived = _close_qa(tmp_path / "w", "agent-qa-hb-waive", _handback_run("CLOSE_REPORT_APPEND_ERROR: append: disk full"))
    assert waived.returncode == 0, waived.stderr
    clash = _close_qa(tmp_path / "c", "agent-qa-hb-clash", _handback_run("CLOSE_FINDINGS: 2 items"))
    assert clash.returncode == 2
    assert "verdict_class_inconsistent" in clash.stderr


def test_the_handback_outranks_a_reply_text(tmp_path):
    proc = _close_qa(tmp_path, "agent-qa-hb-stub", _handback_run("CLOSE: YES"), last_assistant_message="PRE-HANDBACK-TEXT")
    assert proc.returncode == 0, proc.stderr


def test_only_the_delivered_call_counts_when_the_agent_calls_twice(tmp_path):
    run = _handback_run("CLOSE: YES", "two_handbacks_records", second="NOT-A-LEGAL-VERDICT-LINE")
    proc = _close_qa(tmp_path, "agent-qa-hb-twice", run)
    assert proc.returncode == 0, proc.stderr


def test_an_earlier_runs_handback_is_not_this_runs_report(tmp_path):
    proc = _close_qa(tmp_path, "agent-qa-hb-resumed", _handback_run("CLOSE: YES"), _resumed("still working"),
                     last_assistant_message="still working")
    assert proc.returncode == 2
    assert "<response_line>" in proc.stderr


def test_no_handback_and_no_reply_is_refused_as_before(tmp_path):
    proc = _close_qa(tmp_path, "agent-qa-hb-none")
    assert proc.returncode == 2
    assert "<response_line>" in proc.stderr


def test_a_handback_response_block_passes(tmp_path):
    agent_id = "agent-ca-hb-block"
    project, home = base._standard_setup(tmp_path, "changelog-analyst", agent_id)
    body = json.dumps({"commit_status": "nothing_to_commit"})
    path = _transcript(home, project, agent_id, base._response_block_obligation("20260101-000702"),
                       _handback_run(f"{base._CA_BEGIN}\n{body}\n{base._CA_END}\n"))
    proc = _stop(project, home, agent_id, path, agent_type="changelog-analyst")
    assert proc.returncode == 0, proc.stderr


def test_the_producer_gate_passes_a_handback_producer(tmp_path):
    proc = _close_qa(tmp_path, "agent-qa-hb-gate", _handback_run("CLOSE: YES"), hook=GATE)
    assert proc.returncode == 0, proc.stderr


def _track(monkeypatch, payload: dict) -> dict:
    spec = importlib.util.spec_from_file_location("restart_track_under_test", TRACK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seen = {}
    monkeypatch.setattr(module.restart, "observe_subagent_stop", lambda p: seen.update(p))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert module.main() == 0
    return seen


def test_the_restart_tracker_records_the_handback_report(tmp_path, monkeypatch):
    path = tmp_path / "agent.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in FIXTURE["run_start_records"]
                            + _handback_run("RECOVERY_STATUS: quota_interrupted")), encoding="utf-8")
    payload = {**FIXTURE["subagent_stop_payload"], "agent_transcript_path": str(path)}
    seen = _track(monkeypatch, payload)
    assert seen["last_assistant_message"] == "RECOVERY_STATUS: quota_interrupted"


def test_the_restart_tracker_passes_a_reply_payload_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "agent.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in FIXTURE["run_start_records"] + _resumed("done")),
                    encoding="utf-8")
    payload = {**FIXTURE["subagent_stop_payload"], "agent_transcript_path": str(path), "last_assistant_message": "done"}
    assert _track(monkeypatch, payload) == payload


@pytest.mark.parametrize("path", [None, "", "/nonexistent/agent.jsonl", 7])
def test_no_readable_transcript_leaves_the_reply(path):
    assert final_report.handback_message(path) is None
    assert final_report.final_report({"last_assistant_message": "reply", "agent_transcript_path": path}) == "reply"
    assert final_report.final_report({"agent_transcript_path": path}) is None
