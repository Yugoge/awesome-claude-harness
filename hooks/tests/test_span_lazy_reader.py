"""The span and checklist readers read a long transcript once and decode only
what decides (P1b FX4: FX1's CS-1..3 and OB-2).

- command_span.Span keeps the bytes active_span read; Span.iter_calls decodes a
  record only when its reader reaches it, newest first on request.
- todo_canonical.checklist decodes the lists up to the first accepted one; the
  newest ok TodoWrite (with ``before``, the newest ahead of that call) and its
  writes are read only when asked. Every state below reads as the full read of
  every call reads it.
- A reader from the end finds its lines from the end (P1b latency lane): it
  never runs the forward line reader over the span, and with ``before`` it
  decodes the lines holding that id, not every call ahead of it.
- obligation's outcomes and command_span's Call/WriteSet/Span are plain
  classes and namedtuples, so loading them does not import dataclasses.

Run with: python3 -m pytest hooks/tests/test_span_lazy_reader.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS.parent))
from hooks.lib import command_span, obligation, todo_canonical  # noqa: E402


def _canonical(command="dev"):
    out = subprocess.run([sys.executable, str(HOOKS.parent / "scripts" / "todo" / f"{command}.py")],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


DEV = _canonical()


def _frontier(n, done=False, todos=DEV):
    return [dict(t, status="completed" if i < n or (done and i == n) else "in_progress" if i == n else "pending")
            for i, t in enumerate(todos)]


def _opener(command="dev", args="x"):
    return {"type": "user", "message": {"role": "user", "content":
            f"<command-message>{command} is running…</command-message>\n"
            f"<command-name>/{command}</command-name>\n<command-args>{args}</command-args>"}}


def _uses(*calls, sidechain=False):
    record = {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": f"toolu_{i}", "name": name, "input": tool_input} for i, name, tool_input in calls]}}
    if sidechain:
        record["isSidechain"] = True
    return record


def _use(i, todos, sidechain=False):
    return _uses((i, "TodoWrite", {"todos": todos}), sidechain=sidechain)


def _result(*ids, error=False, sidechain=False):
    record = {"type": "user", "message": {"role": "user", "content": [
        dict({"type": "tool_result", "tool_use_id": f"toolu_{i}", "content": "ok"}, **({"is_error": True} if error else {}))
        for i in ids]}}
    if sidechain:
        record["isSidechain"] = True
    return record


STATES = {
    "not-started": [_opener()],
    "refused-first": [_opener(), _use(1, _frontier(0)), _result(1, error=True)],
    "first-breaks-rule": [_opener(), _use(1, _frontier(2)), _result(1)],
    "then-valid": [_opener(), _use(1, _frontier(2)), _result(1), _use(2, _frontier(0)), _result(2)],
    "progressing": [_opener(), _use(1, _frontier(0)), _result(1), _use(2, _frontier(3)), _result(2)],
    "newest-pending": [_opener(), _use(1, _frontier(0)), _result(1), _use(2, _frontier(1))],
    "newest-refused": [_opener(), _use(1, _frontier(0)), _result(1), _use(2, _frontier(1)), _result(2, error=True)],
    "newest-malformed": [_opener(), _use(1, _frontier(0)), _result(1),
                         _use(2, _frontier(1)[:-1] + ["not a step"]), _result(2)],
    "parallel-one-record": [_opener(), _uses((1, "TodoWrite", {"todos": _frontier(0)}),
                                             (2, "TodoWrite", {"todos": _frontier(1)})), _result(1, 2)],
    "subagent-own-todowrite": [_opener(), _use(1, _frontier(0)), _result(1),
                               _use(2, _frontier(5), sidechain=True), _result(2, sidechain=True)],
    "two-break-then-valid": [_opener(), _use(1, _frontier(2)), _result(1), _use(2, _frontier(3)), _result(2),
                             _use(3, _frontier(0)), _result(3), _use(4, _frontier(1)), _result(4)],
    "short-after-accepted": [_opener(), _use(1, _frontier(0)), _result(1), _use(2, _frontier(1, todos=DEV[:-2])),
                             _result(2)],
    "earlier-command": [_opener(), _use(1, _frontier(0)), _result(1), _opener(args="y"), _use(2, _frontier(2)),
                        _result(2)],
    # The first call that has an id is where ``before`` cuts, wherever another one has it too.
    "id-used-twice": [_opener(), _use(1, _frontier(0)), _result(1), _use(2, _frontier(1)), _result(2),
                      _use(3, _frontier(2)), _result(3), _use(2, _frontier(3)), _result(2), _use(4, _frontier(4)),
                      _result(4)],
    "id-twice-in-one-record": [_opener(), _use(1, _frontier(0)), _result(1),
                               _uses((3, "TodoWrite", {"todos": _frontier(1)}), (2, "TodoWrite", {"todos": _frontier(2)}),
                                     (3, "TodoWrite", {"todos": _frontier(3)})), _result(3, 2)],
    "id-on-another-tool": [_opener(), _use(1, _frontier(0)), _result(1), _uses((3, "Agent", {"prompt": "p"})),
                           _result(3), _use(2, _frontier(1)), _result(2), _use(3, _frontier(2)), _result(3)],
    "result-before-use": [_opener(), _use(1, _frontier(0)), _result(1), _result(2), _use(2, _frontier(1)), _result(2),
                          _use(3, _frontier(2)), _result(3)],
}


def _write(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def _full_read(path, before=None):
    """The checklist as a read of every call of the span gives it."""
    span = command_span.active_span(path)
    todos, writes = None, []
    for call in span.calls("TodoWrite"):
        if before and call.id == before:
            break
        new = call.input.get("todos")
        if not call.ok or not isinstance(new, list) or not all(isinstance(t, dict) for t in new):
            continue
        todos = new
        if writes or not todo_canonical.initial_status_violations(new):
            writes.append(call)
    accepted = writes[-1].input["todos"] if writes else None
    lock = ("not_started" if todos is None else "count_mismatch" if len(todos) < len(DEV)
            else "sequence_violation" if not writes else "")
    return todos, accepted, lock, tuple(writes)


@pytest.fixture(autouse=True)
def _harness_scripts(tmp_path, monkeypatch):
    # A project without scripts/todo: the canonical list is the harness's own.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))


IDS = [None] + [f"toolu_{i}" for i in range(1, 5)] + ["toolu_9", "toolu_odd/1", "toolu_\u00e9"]


@pytest.mark.parametrize("state", sorted(STATES))
def test_checklist_reads_as_the_full_read(tmp_path, state):
    path = _write(tmp_path / "t.jsonl", STATES[state])
    for before in IDS:
        got = todo_canonical.checklist(path, before)
        assert (got.todos, got.accepted, got.lock, got.writes) == _full_read(path, before), (state, before)


def _ahead_of(calls, before):
    """calls up to the first one that has id ``before``, as the full read cuts them."""
    out = []
    for call in calls:
        if before and call.id == before:
            break
        out.append(call)
    return out


@pytest.mark.parametrize("state", sorted(STATES))
def test_iter_calls_newest_first_is_calls_reversed(tmp_path, state):
    span = command_span.active_span(_write(tmp_path / "t.jsonl", STATES[state]))
    for names in (("TodoWrite",), ("Agent", "Task"), ()):
        for before in IDS:
            ahead = _ahead_of(span.calls(*names), before)
            assert list(span.iter_calls(*names, newest_first=True, before=before)) == list(reversed(ahead)), \
                (names, before)
            assert list(span.iter_calls(*names, before=before)) == ahead, (names, before)
        assert list(span.iter_calls(*names)) == span.calls(*names)


@pytest.mark.parametrize("state", sorted(STATES))
def test_a_span_built_without_its_bytes_reads_from_the_end_alike(tmp_path, state):
    path = _write(tmp_path / "t.jsonl", STATES[state])
    read = command_span.active_span(path)
    unread = command_span.Span(read.command, read.args, read.start_line, str(path))
    for before in IDS:
        assert list(unread.iter_calls("TodoWrite", newest_first=True, before=before)) == \
            list(read.iter_calls("TodoWrite", newest_first=True, before=before))


def test_a_reader_from_the_end_never_runs_the_forward_reader_over_the_span(tmp_path, monkeypatch):
    records = [_opener()]
    for i in range(1, 41):
        records += [_use(i, _frontier(min(i - 1, len(DEV) - 1))), _result(i)]
    span = command_span.active_span(_write(tmp_path / "t.jsonl", records))
    real = command_span._Lines.having

    def having(self, needles, after=0, start=0, unless=b""):
        assert start > 0, "a forward read from the top of the transcript"  # only a call's result search runs forward
        return real(self, needles, after, start, unless)

    monkeypatch.setattr(command_span._Lines, "having", having)
    newest = next(span.iter_calls("TodoWrite", newest_first=True))
    assert (newest.id, newest.line, newest.ok) == ("toolu_40", len(records) - 1, True)
    assert next(span.iter_calls("TodoWrite", newest_first=True, before="toolu_40")).id == "toolu_39"


def test_a_checklist_ahead_of_a_call_decodes_the_lines_holding_its_id(tmp_path, monkeypatch):
    records = [_opener()]
    for i in range(1, 41):
        records += [_use(i, _frontier(min(i - 1, len(DEV) - 1))), _result(i)]
    path = _write(tmp_path / "t.jsonl", records)
    decoded = []
    real = command_span._decode
    monkeypatch.setattr(command_span, "_decode", lambda raw: decoded.append(raw) or real(raw))
    state = todo_canonical.checklist(path, "toolu_40")  # the PostToolUse of the newest TodoWrite
    assert state.todos == records[-4]["message"]["content"][0]["input"]["todos"] and state.lock == ""
    uses = [raw for raw in decoded if b'"tool_use"' in raw]
    assert len(uses) == 3, "the call with the id, the first accepted list and the newest one ahead of it"


@pytest.mark.parametrize("before", [None, "toolu_9"])
def test_the_step_rules_still_raise_inside_checklist(tmp_path, before):
    broken = [{"status": "completed", "activeForm": "x"}] + _frontier(0)[1:]  # a completed step with no content
    path = _write(tmp_path / "t.jsonl", [_opener(), _use(1, broken), _result(1), _use(9, _frontier(0)), _result(9)])
    with pytest.raises(KeyError):
        todo_canonical.checklist(path, before)


def test_checklist_decodes_only_the_deciding_lists(tmp_path, monkeypatch):
    records = [_opener()]
    for i in range(1, 41):
        records += [_use(i, _frontier(min(i - 1, len(DEV) - 1))), _result(i)]
    path = _write(tmp_path / "t.jsonl", records)
    decoded = []
    real = command_span._decode
    monkeypatch.setattr(command_span, "_decode", lambda raw: decoded.append(raw) or real(raw))
    state = todo_canonical.checklist(path)
    assert len([raw for raw in decoded if b'"tool_use"' in raw]) == 1, "the first accepted list"
    assert state.todos == records[-2]["message"]["content"][0]["input"]["todos"] and state.lock == ""
    assert len([raw for raw in decoded if b'"tool_use"' in raw]) == 2, "and, once asked, the newest ok list"
    decoded.clear()
    assert len(state.writes) == 40
    assert len([raw for raw in decoded if b'"tool_use"' in raw]) == 40


def test_span_reads_the_transcript_once(tmp_path):
    path = _write(tmp_path / "t.jsonl", STATES["progressing"])
    span = command_span.active_span(path)
    with path.open("a") as handle:  # the CLI appends after the read
        handle.write(json.dumps(_use(9, _frontier(4))) + "\n" + json.dumps(_result(9)) + "\n")
    assert [c.id for c in span.calls("TodoWrite")] == ["toolu_1", "toolu_2"]
    assert span == command_span.Span(span.command, span.args, span.start_line)
    assert repr(span) == f"Span(command='dev', args='x', start_line={span.start_line})"


def test_outcomes_compare_hash_and_freeze_as_the_dataclasses_did():
    assert obligation.Rejection("r") == obligation.Rejection(reason="r", field="", detail="", outcome="rejected")
    assert obligation.Rejection("r") != obligation.Unresolvable("r")
    assert hash(obligation.NoBlock()) == hash(("no_block",))
    assert repr(obligation.Unresolvable("r", prompt="p")) == \
        "Unresolvable(reason='r', detail='', outcome='unresolvable', prompt='p')"
    with pytest.raises(AttributeError, match="cannot assign to field 'reason'"):
        obligation.Rejection("r").reason = "s"
    with pytest.raises(TypeError):
        hash(obligation.ParsedObligation({"role": "dev"}))
    with pytest.raises(TypeError, match="missing 1 required positional argument: 'reason'"):
        obligation.Unresolvable()


def test_span_and_obligation_load_without_dataclasses():
    code = ("import sys; sys.path.insert(0, sys.argv[1]); "
            "import lib.command_span, lib.todo_canonical, lib.obligation; print('dataclasses' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code, str(HOOKS)], capture_output=True, text=True, check=True,
                         env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert out.stdout.strip() == "False"
