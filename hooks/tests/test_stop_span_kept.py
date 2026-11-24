"""The span reader reads the session's own conversation from where the last stop stopped (command_span, lib/transcript_index).

1. Inside a scan that keeps its readings, what the reader of command spans returns (the open command, its span's start,
   the dispatches with their results and times, the families, the obligations) is what a whole read returns, in every
   case: results that come later, a call a hook refused, a result that is an error, prompts typed in the span, a /stop,
   a compaction, a second command opening a new span, an unfinished last line; a file that is no continuation is read
   whole again and gives the same.
2. What a stop reads is counted, never timed: after a small addition it is the addition and a fixed check, the same at
   two sizes of conversation.
Conversations are made up here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from hooks.lib import command_span, obligation, transcript_index  # noqa: E402

TASK = "20261101-100000"
OTHER = "20261101-110000"


def _doc(task, role, at):
    return {"task_id": task, "lane": None, "lane_set": None, "role": role, "pipeline": "dev", "profile": "singular",
            "dispatched_at": at,
            "artifacts": [{"kind": "json", "path": f"docs/dev/context-{task}.json", "schema": "context.v1",
                           "identity": {"task_id": task}}]}


def _dispatch(use_id, task, role="ba", at="2026-11-01T10:00:00Z"):
    prompt = "FIRST ACTION: register.\n" + obligation.serialize_obligation(_doc(task, role, at))
    return {"type": "assistant", "timestamp": at, "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": use_id, "name": "Agent", "input": {"subagent_type": role, "prompt": prompt}}]}}


def _result(use_id, error=False):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": use_id, "content": "done", "is_error": error}]}}


def _refused(use_id):
    return {"type": "user", "permissionDecision": {"decision": "reject", "source": "hook"},
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": use_id, "content": "no"}]}}


def _typed(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _compaction():
    return {"type": "user", "isCompactSummary": True, "message": {"role": "user", "content": "/dev summary of before"}}


def _lines(*records):
    return "".join(json.dumps(r) + "\n" for r in records)


def _filler(size):
    line = json.dumps({"type": "user", "message": {"role": "user", "content": "chatter " * 12}}) + "\n"
    return line * max(1, size // len(line))


def _view(path, keep):
    """What the reader of command spans gives for ``path``, in a scan that keeps its readings in ``keep`` (or reads whole),
    and the scan."""
    with obligation.transcript_scan(keep=keep) as scan:
        span = command_span.active_span(path)
        if span is None:
            return None, scan
        shown = {
            "span": (span.command, span.args, span.start_line),
            "dispatches": [(tuple(c), doc) for c, doc in span.dispatches()],
            "obligations": [(tuple(c), doc) for c, doc in span.obligations()],
            "families": span.session_families(),
            "calls": [tuple(c) for c in span.dispatch_calls()],
        }
        return shown, scan


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return tmp_path


def _same(path, keep):
    kept, scan = _view(path, keep)
    whole, _ = _view(path, None)
    assert kept == whole
    return kept, scan


STAGES = {
    "results come later": [
        [_typed("/dev go"), _dispatch("t1", TASK), _typed("a plain prompt in the span")],
        [_result("t1"), _dispatch("t2", TASK, "qa")],
        [_result("t2", error=True)],
    ],
    "a call a hook refused": [
        [_typed("/dev go"), _dispatch("t1", TASK), _dispatch("t2", OTHER)],
        [_refused("t1"), _result("t2")],
    ],
    "an owner's stop": [
        [_typed("/dev go"), _dispatch("t1", TASK), _result("t1")],
        [_typed("/stop"), _dispatch("t2", TASK, "qa")],
        [_result("t2")],
    ],
    "a compaction": [
        [_typed("/dev go"), _dispatch("t1", TASK)],
        [_compaction(), _result("t1"), _dispatch("t2", TASK, "dev")],
        [_result("t2")],
    ],
    "a second command opens a new span": [
        [_typed("/dev go"), _dispatch("t1", TASK), _result("t1")],
        [_typed("/close"), _dispatch("t2", OTHER, "qa")],
        [_result("t2"), _dispatch("t3", OTHER, "dev")],
    ],
}


@pytest.mark.parametrize("case", sorted(STAGES))
def test_the_kept_reading_returns_what_a_whole_read_returns(home, case):
    path = home / "live.jsonl"
    keep = home / "state"
    path.write_text("")
    for stage in STAGES[case]:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(_lines(*stage))
        _same(path, keep)  # after every addition, with what the stops before kept
    half = json.dumps(_dispatch("t9", TASK, "qa"))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(half[:50])  # an unfinished last line: a whole read takes it as it is
    _same(path, keep)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(half[50:] + "\n")
    shown, _ = _same(path, keep)
    assert shown is not None and any(call[0] == "t9" for call, _doc in shown["dispatches"])


def test_the_kept_reading_finds_the_results_the_first_stop_did_not_have(home):
    path = home / "live.jsonl"
    keep = home / "state"
    path.write_text(_lines(_typed("/dev go"), _dispatch("t1", TASK)))
    first, _ = _same(path, keep)
    assert first["dispatches"][0][0][4:] == (0, False)  # (result_line, ok): none yet
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(_lines(_typed("noted"), _result("t1")))
    later, _ = _same(path, keep)
    assert later["dispatches"][0][0][4:] == (4, True)


@pytest.mark.parametrize("change", ["shorter", "changed_before", "replaced"])
def test_a_file_that_is_no_continuation_is_read_whole_again(home, change):
    path = home / "live.jsonl"
    keep = home / "state"
    body = _lines(_typed("/dev go"), _dispatch("t1", TASK)) + _filler(200_000) + _lines(_dispatch("t2", TASK, "qa"))
    path.write_text(body)
    _same(path, keep)
    if change == "shorter":
        path.write_text(body[:len(body) // 2])
    elif change == "changed_before":  # the same size, an early byte different
        path.write_text(body.replace(TASK, OTHER, 1))
    else:
        path.write_text(_lines(_typed("/close other"), _dispatch("n1", OTHER, "dev")) + _filler(300_000))
    shown, scan = _same(path, keep)
    assert shown is not None
    assert scan.bytes >= path.stat().st_size  # read whole, not from the old offset


def _read_after_a_small_addition(base, size, monkeypatch):
    base.mkdir()
    path = base / "live.jsonl"
    keep = base / "state"
    path.write_text(_lines(_typed("/dev go"), _dispatch("t1", TASK)) + _filler(size) + _lines(_result("t1")))
    _same(path, keep)
    _, unchanged = _view(path, keep)
    addition = _lines(_dispatch("t2", TASK, "qa"), _typed("noted"), _result("t2"))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(addition)
    def whole_read(*_args, **_kw):
        raise AssertionError("the conversation was read whole")

    with monkeypatch.context() as spy:  # the reads of the whole file, and the search from its end, are not made
        spy.setattr(command_span, "_read", whole_read)
        spy.setattr(command_span, "_last_opener", whole_read)
        shown, scan = _view(path, keep)
    assert shown == _view(path, None)[0]
    assert [call[0] for call, _doc in shown["dispatches"]] == ["t1", "t2"]
    _, again = _view(path, keep)
    return unchanged.bytes, scan.bytes, again.bytes, len(addition)


def test_a_stop_after_a_small_addition_reads_the_addition_not_the_conversation(home, monkeypatch):
    small = _read_after_a_small_addition(home / "a", 1_000_000, monkeypatch)
    large = _read_after_a_small_addition(home / "b", 5_000_000, monkeypatch)  # five times the length
    assert small[1] >= small[3] and large[1] >= large[3]  # the addition was read, and counted
    assert small[1] - small[3] == large[1] - large[3]  # the same fixed check, whatever the length
    assert large[1] < 5_000_000 // 10  # a tenth of the conversation, not the conversation
    assert small[0] == large[0] == small[2] == large[2]  # nothing added: that check only
    assert small[0] <= 2 * transcript_index.WINDOW * 2


def test_the_latest_command_is_read_from_what_was_kept_and_equals_a_whole_read(home):
    """The coordinator's reader (active_command with a folder to keep in): the same answer as the whole read, and
    after a small addition it reads the addition, not the conversation."""
    path = home / "live.jsonl"
    keep = home / "state"
    path.write_text(_lines(_typed("/dev go"), _dispatch("t1", TASK)) + _filler(2_000_000))
    assert command_span.active_command(path, keep=keep) == command_span.active_command(path) == "dev"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(_lines(_typed("/close"), _typed("noted")))
    reads = []
    real = transcript_index.extend

    def counted(*args):
        got = real(*args)
        reads.append(got[1])
        return got

    with pytest.MonkeyPatch.context() as spy:
        spy.setattr(transcript_index, "extend", counted)
        assert command_span.active_command(path, keep=keep) == command_span.active_command(path) == "close"
    assert len(reads) == 1 and reads[0] <= 4 * transcript_index.WINDOW + 1024  # the addition and the fixed check, not the 2 MB
