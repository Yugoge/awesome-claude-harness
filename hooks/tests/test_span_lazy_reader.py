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


# -- the span read from the end of the transcript (P1b latency, review item 2) ---------------------------

def _forward_span(path):
    """The span as a read of the whole transcript from its top finds it: the last line that holds a user
    record and no tool result and opens a span (the reader before the from-the-end one)."""
    data = path.read_bytes()
    found, pos, number = None, 0, 0
    for raw in data.split(b"\n"):
        number += 1
        if any(n in raw for n in command_span._USER_RECORD) and command_span._RESULT_BLOCK not in raw:
            record = command_span._decode(raw)
            opener = command_span.stop_contract.span_opener(record, command_span.stop_contract.harness_commands()) \
                if record else None
            if opener:
                found = (opener[0], opener[1], number)
        pos += len(raw) + 1
    return found


class _Counted:
    """A file object that counts the bytes read through it."""

    def __init__(self, handle, counter):
        self._handle, self._counter = handle, counter

    def read(self, *size):
        out = self._handle.read(*size)
        self._counter.append(len(out))
        return out

    def __getattr__(self, name):
        return getattr(self._handle, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._handle.close()


def _long_session(tmp_path, rounds=60, typed_again=True):
    """An earlier /dev's checklist, then (when typed_again) a later /dev whose span is the last records."""
    records = [_opener()]
    for i in range(1, rounds + 1):
        records += [_use(i, _frontier(min(i - 1, len(DEV) - 1))), _result(i)]
    if typed_again:
        records += [_opener(args="later")]
        records += [_use(900, _frontier(0)), _result(900), _use(901, _frontier(1)), _result(901),
                    _uses((902, "Agent", {"subagent_type": "ba", "prompt": "p"})), _result(902)]
    return _write(tmp_path / "long.jsonl", records), records


@pytest.mark.parametrize("chunk", [64, 4096, 1 << 20])
def test_a_span_read_from_the_end_reads_no_line_before_it(tmp_path, monkeypatch, chunk):
    path, records = _long_session(tmp_path)
    monkeypatch.setattr(command_span, "_TAIL_CHUNK", chunk, raising=False)
    read = []
    real_open = open
    monkeypatch.setattr(command_span, "open", lambda p, *a, **k: _Counted(real_open(p, *a, **k), read), raising=False)
    span = command_span.active_span(path)
    tail = sum(len(json.dumps(r)) + 1 for r in records[-7:])
    if chunk < tail:  # the span is larger than one chunk: only the chunks back to its opener are read
        assert sum(read) < path.stat().st_size / 2, "the reader read the lines before the span"
    monkeypatch.setattr(command_span, "open", real_open, raising=False)
    assert (span.command, span.args, span.start_line) == _forward_span(path)
    state = todo_canonical.checklist(path)
    assert (state.todos, state.accepted, state.lock, state.writes) == _full_read(path)
    assert [c.id for c in state.span.calls()] == ["toolu_900", "toolu_901", "toolu_902"]


def test_the_lines_before_the_span_are_numbered_only_when_asked(tmp_path, monkeypatch):
    path, records = _long_session(tmp_path, rounds=40)
    monkeypatch.setattr(command_span, "_TAIL_CHUNK", 256, raising=False)
    span = command_span.active_span(path)
    assert span._start_line is None, "the reader counted the lines before the span"
    assert list(span.uses("TodoWrite")) and span._start_line is None
    assert span.start_line == len(records) - 6
    assert [c.line for c in span.calls("TodoWrite")] == [len(records) - 5, len(records) - 3]


@pytest.mark.parametrize("state", sorted(STATES))
def test_uses_are_the_calls_without_line_numbers(tmp_path, state):
    span = command_span.active_span(_write(tmp_path / "t.jsonl", STATES[state]))
    data = (tmp_path / "t.jsonl").read_bytes()
    starts = [0] + [i + 1 for i, b in enumerate(data) if b == 10]
    for names in (("TodoWrite",), ("Agent", "Task"), ()):
        for before in IDS:
            for newest_first in (False, True):
                calls = list(span.iter_calls(*names, newest_first=newest_first, before=before))
                uses = list(span.uses(*names, newest_first=newest_first, before=before))
                assert [(c.id, c.name, c.input, c.ok) for c in calls] == [(u.id, u.name, u.input, u.ok) for u in uses]
                # a result's offset is the start of the line its line number names
                assert [starts[c.result_line - 1] if c.result_line else None for c in calls] == \
                    [u.result_at for u in uses], (names, before, newest_first)


@pytest.mark.parametrize("state", sorted(STATES))
def test_the_checklist_readers_never_number_a_line(tmp_path, monkeypatch, state):
    # Line numbers count the lines before the span; no checklist decision needs one.
    path = _write(tmp_path / "t.jsonl", STATES[state])
    expected = {before: _full_read(path, before) for before in IDS}
    guard = _load_hook("pretool-todo-validate.py")
    reference = {}
    for before in IDS:
        st = todo_canonical.checklist(path, before)
        reference[before] = _dispatched_by_lines(st, DEV) if st else None
    monkeypatch.setattr(command_span.Span, "start_line", property(lambda self: pytest.fail("a line was numbered")))
    for before in IDS:
        got = todo_canonical.checklist(path, before)
        assert (got.todos, got.accepted, got.lock) == expected[before][:3]
        assert [w.id for w in got.write_uses] == [w.id for w in expected[before][3]]
        assert guard._dispatched_steps(got, DEV) == reference[before]


def _load_hook(name):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name.replace("-", "_")[:-3], HOOKS / name)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(HOOKS))
    spec.loader.exec_module(module)
    return module


def _dispatched_by_lines(state, canonical):
    """todo-validate's dispatched steps as the reader that ordered results by line number read them."""
    guard = _load_hook("pretool-todo-validate.py")
    events = sorted([(w.result_line, 0, w) for w in state.writes]
                    + [(c.result_line, 1, c) for c in state.span.calls("Agent", "Task") if c.ok],
                    key=lambda e: (e[0], e[1]))
    current, counted = [], set()
    for _, is_dispatch, call in events:
        if not is_dispatch:
            current = call.input["todos"]
            counted -= {i for i, t in enumerate(current) if t.get("status") == "pending"}
            continue
        ip = guard._in_progress(current)
        if ip is None:
            continue
        kind = str(call.input.get("subagent_type") or "").strip().lower()
        window = range(ip, min(len(canonical), ip + 3)) if kind else [ip]
        for i in window:
            types = guard._subagent_types(canonical[i]) if i < len(canonical) else set()
            if types and i not in counted and (not kind or kind in types):
                counted.add(i)
                break
    return counted


OPENER_LINES = {
    # a user record holding a tool result late in its line is a result, never typed
    "result-late": [_opener(), {"type": "user", "message": {"role": "user", "content": [
        {"type": "text", "text": "x" * 300}, {"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}}],
    # the next line's result does not make this one a result
    "result-next-line": [_opener(args="first"), _opener(args="second"), _result(1)],
    "spaced-and-compact": [_opener(args="a"), "COMPACT:" + json.dumps(_opener(args="b"), separators=(",", ":"))],
    "user-word-in-assistant": [_opener(args="a"), _uses((1, "Bash", {"command": "x", "user": "y"}))],
    "last-line-unterminated": [_opener(args="a"), "NOEOL:" + json.dumps(_opener(args="b"))],
    "only-results": [_result(1), _result(2)],
    "empty": [],
}


@pytest.mark.parametrize("chunk", [16, 97, 4096])
@pytest.mark.parametrize("name", sorted(OPENER_LINES))
def test_the_opener_from_the_end_is_the_last_one_from_the_top(tmp_path, monkeypatch, name, chunk):
    lines = []
    for r in OPENER_LINES[name]:
        if isinstance(r, str) and r.startswith("COMPACT:"):
            lines.append(r[len("COMPACT:"):] + "\n")
        elif isinstance(r, str) and r.startswith("NOEOL:"):
            lines.append(r[len("NOEOL:"):])
        else:
            lines.append(json.dumps(r) + "\n")
    path = tmp_path / "t.jsonl"
    path.write_text("".join(lines))
    monkeypatch.setattr(command_span, "_TAIL_CHUNK", chunk, raising=False)
    span = command_span.active_span(path)
    expected = _forward_span(path)
    assert (None if span is None else (span.command, span.args, span.start_line)) == expected


def test_obligation_loads_without_tempfile_or_hashlib():
    # Every hook that reads an obligation imports subagent_restart; only its state writer and its token
    # mint use tempfile and hashlib, so they are imported there.
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import lib.obligation; "
            "print(sorted(m for m in ('tempfile', 'hashlib') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code, str(HOOKS)], capture_output=True, text=True, check=True,
                         env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert out.stdout.strip() == "[]"
