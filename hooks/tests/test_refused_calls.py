"""command_span.refused_calls: the one definition of "a hook refused this tool call" (it never ran).

A PreToolUse hook's refusal reaches two records: the refusal record (lib/refusal_record.py), written by the
refusing hook before it exits, and the CLI's tool_result for the call, written after, whose record carries
permissionDecision {"decision": "reject", "source": "hook"} (CLI 2.1.322). A sibling call of the same assistant
message can be asked about between the two, so the reader takes either. A call cut off, a call that failed
and a call whose result has not come back are not refused.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "hooks"))
from lib import command_span  # noqa: E402
from tests.cli_shapes import synthesize  # noqa: E402

SID = "11111111-2222-3333-4444-555555555555"


def _use(ident: str) -> dict:
    rec = synthesize("assistant", "tool_use")
    next(b for b in rec["message"]["content"] if b["type"] == "tool_use").update(id=ident, name="Agent", input={})
    return rec


def _result(ident: str, variant: str = "tool_result", hook: bool = False) -> dict:
    rec = synthesize("user", variant)
    next(b for b in rec["message"]["content"] if b["type"] == "tool_result")["tool_use_id"] = ident
    if hook:
        rec["permissionDecision"] = {"decision": "reject", "source": "hook", "reasonType": "hook",
                                     "reasonCode": "hook:PreToolUse"}
    return rec


def _transcript(tmp_path: Path, records: list) -> Path:
    path = tmp_path / f"{SID}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def test_a_call_whose_result_the_cli_recorded_as_a_hook_refusal_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    path = _transcript(tmp_path, [_use("toolu_ran"), _result("toolu_ran"), _use("toolu_refused"),
                                  _result("toolu_refused", hook=True), _use("toolu_cut"), _result("toolu_cut", "cut"),
                                  _use("toolu_running")])
    assert command_span.refused_calls(str(path)) == {"toolu_refused"}


def test_a_sibling_refused_before_its_result_is_written_is_refused_from_the_refusal_record(tmp_path, monkeypatch):
    """Two Agent calls of one message: the first one's hook refused it and wrote the refusal record; the CLI has
    not written its result when the second one's hooks read the transcript."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    path = _transcript(tmp_path, [_use("toolu_first"), _use("toolu_second")])
    assert command_span.refused_calls(str(path)) == frozenset()
    day = Path(command_span._refusal_record_files(time.time())[-1])
    day.parent.mkdir(parents=True)
    lines = [{"v": 1, "kind": "refusal", "event": "PreToolUse", "session": SID, "tool_use_id": "toolu_first"},
             {"v": 1, "kind": "refusal", "event": "PostToolUse", "session": SID, "tool_use_id": "toolu_second"},
             {"v": 1, "kind": "unproven", "event": "PreToolUse", "session": SID, "tool_use_id": "toolu_second"},
             {"v": 1, "kind": "refusal", "event": "PreToolUse", "session": "another", "tool_use_id": "toolu_second"}]
    day.write_text("".join(json.dumps(l) + "\n" for l in lines))
    assert command_span.refused_calls(str(path)) == {"toolu_first"}
    assert command_span.refused_calls(str(path), "another") == {"toolu_second"}


def test_an_unreadable_source_adds_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert command_span.refused_calls(str(tmp_path / "missing.jsonl")) == frozenset()
    assert command_span.refused_calls(None) == frozenset()


def test_the_records_a_reader_holds_give_the_same_refused_calls_as_the_file(tmp_path, monkeypatch):
    """A reader that already holds the transcript's bytes (a Span) or its records (subagent_restart's parent
    reading, for dispatch_obligations) asks the same one test, hook_refused, without opening the file again."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    records = [_use("toolu_ran"), _result("toolu_ran"), _use("toolu_refused"), _result("toolu_refused", hook=True)]
    path = _transcript(tmp_path, records)
    assert command_span.refused_calls(str(path), data=path.read_bytes()) == command_span.refused_calls(str(path)) \
        == {"toolu_refused"}
    assert [i for r in records for i in command_span.hook_refused(r)] == ["toolu_refused"]
