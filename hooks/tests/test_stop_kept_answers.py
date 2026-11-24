"""A kept result of the Stop gate is out of date only when something it was computed from changed (lib/fact_cache).

1. What a computation asked of the saved conversations (the dispatch records of a task, obligation._task_records)
   is kept by the answer's digest: a conversation that grew without changing the answer discards nothing, one
   whose growth changes the answer (a new dispatch, a hook's refusal of one, a new conversation naming the task)
   does; a fact read any other way (a file) still counts as it did.
2. The stats kept beside the answers are renewed when the answers held, so the next stop asks nothing again.
3. What a stop reads and computes again after a small addition to the session's own conversation is a function
   of the addition (counted, never timed), the same at two sizes of history.
Conversations are made up here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from hooks.lib import fact_cache, obligation, transcript_index  # noqa: E402,F401
from hooks.lib.subagent_restart import project_slug  # noqa: E402

TASK = "20261101-100000"
RESULT = ["GAP made-up"]


def _dispatch(use_id, task=TASK):
    doc = {"task_id": task, "lane": None, "lane_set": None, "role": "ba", "pipeline": "dev", "profile": "singular",
           "dispatched_at": "2026-11-01T10:00:00Z",
           "artifacts": [{"kind": "json", "path": f"docs/dev/context-{task}.json", "schema": "context.v1",
                          "identity": {"task_id": task}}]}
    prompt = "FIRST ACTION: register.\n" + obligation.serialize_obligation(doc)
    return {"type": "assistant", "timestamp": "2026-11-01T10:00:00Z", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": use_id, "name": "Agent", "input": {"subagent_type": "ba", "prompt": prompt}}]}}


def _refused(use_id):
    return {"type": "user", "permissionDecision": {"decision": "reject", "source": "hook"},
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": use_id, "content": "no"}]}}


def _chatter(size):
    line = json.dumps({"type": "user", "message": {"role": "user", "content": "chatter " * 12}}) + "\n"
    return line * max(1, size // len(line))


def _lines(*records):
    return "".join(json.dumps(r) + "\n" for r in records)


class Store:
    def __init__(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir(parents=True)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.project = tmp_path / "proj"
        self.project.mkdir()
        self.root = tmp_path / "projects"
        self.folder = self.root / project_slug(self.project)
        self.folder.mkdir(parents=True)
        self.keep = tmp_path / "state"
        (tmp_path / "rec").mkdir()
        self.record = tmp_path / "rec" / "kept.json"  # in a folder of its own: the temp folder's own mtime is a fact
        self.other = tmp_path / "rec" / "other.txt"
        self.other.write_text("a fact read as a file")

    def write(self, name, text, mode="w"):
        path = self.folder / f"{name}.jsonl"
        with open(path, mode, encoding="utf-8") as handle:
            handle.write(text)
        return path

    def compute(self):
        """One computation as the gate's disposition runs it: in a scan that keeps, watched, then saved."""
        with obligation.transcript_scan(keep=self.keep):
            with fact_cache.watch() as reads:
                records = obligation._task_records(TASK, self.project, [self.root])
                self.other.read_text()
            key = fact_cache.facts(reads, REPO)
        fact_cache.save(self.record, key, RESULT)
        return records, key

    def load(self):
        with obligation.transcript_scan(keep=self.keep) as scan:
            return fact_cache.load(self.record, REPO), scan


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = Store(tmp_path, monkeypatch)
    s.own = s.write("own", _lines(_dispatch("toolu_1")) + _chatter(20000))
    s.side = s.write("side", _chatter(5000))
    s.compute()
    return s


def test_a_conversation_that_grew_without_changing_the_answer_keeps_the_result(store):
    assert store.load()[0] == RESULT
    store.write("own", _chatter(300), "a")
    store.write("side", _chatter(300), "a")
    assert store.load()[0] == RESULT


def test_the_keys_conversation_stats_are_not_path_facts(store):
    key = json.loads(store.record.read_text())["key"]
    assert not [p for p in key["paths"] if p.endswith(".jsonl") or "transcript-index" in p]
    assert sorted(Path(p).name for p in key["transcripts"] if p.endswith(".jsonl")) == ["own.jsonl", "side.jsonl"]
    assert key["answers"] and key["answers"][0][0] == TASK


@pytest.mark.parametrize("change", ["a new dispatch", "a hook's refusal", "a new conversation", "a file read"])
def test_what_changes_the_answer_or_another_fact_discards_the_result(store, change):
    if change == "a new dispatch":
        store.write("own", _lines(_dispatch("toolu_2")), "a")
    elif change == "a hook's refusal":
        store.write("own", _lines(_refused("toolu_1")), "a")
    elif change == "a new conversation":
        store.write("third", _lines(_dispatch("toolu_9")))
    else:
        store.other.write_text("changed, and longer")
    assert store.load()[0] is None


def test_a_held_answer_renews_the_stats_so_the_next_stop_asks_nothing(store, monkeypatch):
    store.write("own", _chatter(300), "a")
    assert store.load()[0] == RESULT  # asks the answer, renews the record
    asked = []
    real = obligation._family_records
    monkeypatch.setattr(obligation, "_family_records", lambda *a, **k: asked.append(a[0]) or real(*a, **k))
    assert store.load()[0] == RESULT
    assert asked == []


def test_the_result_after_growth_equals_a_computation_from_scratch(store):
    store.write("own", _chatter(300), "a")
    kept, _ = store.load()
    again, _ = store.compute(), None
    assert kept == RESULT and again[0] == obligation._task_records(TASK, store.project, [store.root])


def _reads_after_a_small_addition(tmp_path, monkeypatch, history):
    """(bytes the scan read, bytes indexed, families asked) by a load after 240 bytes were added to a conversation of
    ``history`` bytes."""
    s = Store(tmp_path, monkeypatch)
    s.write("own", _lines(_dispatch("toolu_1")) + _chatter(history))
    s.write("side", _chatter(3000))
    s.compute()
    s.write("own", _chatter(240), "a")
    runs, family = [], []
    real_runs, real_family = obligation._id_runs, obligation._family_records
    monkeypatch.setattr(obligation, "_id_runs", lambda data: runs.append(len(data)) or real_runs(data))
    monkeypatch.setattr(obligation, "_family_records", lambda *a, **k: family.append(a[0]) or real_family(*a, **k))
    kept, scan = s.load()
    assert kept == RESULT
    return scan.bytes, sum(runs), len(family)


def test_after_a_small_addition_what_a_stop_reads_is_a_function_of_the_addition(tmp_path, monkeypatch):
    small = _reads_after_a_small_addition(tmp_path / "a", monkeypatch, 200_000)
    large = _reads_after_a_small_addition(tmp_path / "b", monkeypatch, 2_000_000)
    assert small == large  # the same at ten times the history
    read, indexed, asked = large
    assert indexed < 400 and asked == 1  # the addition's bytes, and the one family asked once
    assert read < 9 * transcript_index.WINDOW  # the addition and the kept readings' fixed checks (two windows, taken
    # twice, for each of two kinds), never the history: 2 MB here


# ---- the dispatch records of the session's own conversation, asked directly (obligation.dispatch_obligations)
def _typed(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _records_after_an_addition(tmp_path, monkeypatch, history):
    """(bytes the scan read, whole reads made, the records) of dispatch_obligations in a keeping scan after 240 bytes were
    added to a conversation of ``history`` bytes whose earlier stop kept its reading; the records equal a whole read's."""
    s = Store(tmp_path, monkeypatch)
    path = s.write("own", _lines(_dispatch("toolu_1"), _dispatch("toolu_2")) + _chatter(history))
    with obligation.transcript_scan(keep=s.keep):
        obligation.dispatch_obligations(path)
    s.write("own", _lines(_refused("toolu_1")) + _chatter(240), "a")
    whole_reads = []
    real = obligation._read_parent_calls
    monkeypatch.setattr(obligation, "_read_parent_calls", lambda p: whole_reads.append(p) or real(p))
    with obligation.transcript_scan(keep=s.keep) as scan:
        records = obligation.dispatch_obligations(path)
        again = obligation.dispatch_obligations(path)  # a second ask in the scan reads nothing
    assert records == again
    monkeypatch.undo()
    assert records == obligation._whole_dispatch_obligations(path)
    assert [r["tool_use_id"] for r in records] == ["toolu_2"]  # the refused call is no dispatch
    return scan.bytes, len(whole_reads)


def test_the_direct_reader_of_dispatch_records_reads_the_addition_only(tmp_path, monkeypatch):
    small = _records_after_an_addition(tmp_path / "a", monkeypatch, 200_000)
    large = _records_after_an_addition(tmp_path / "b", monkeypatch, 2_000_000)
    assert small == large and large[1] == 0 and large[0] < 9 * transcript_index.WINDOW


def test_a_dispatch_prompt_is_parsed_once_for_a_scan_whoever_asks(tmp_path, monkeypatch):
    from hooks.lib import command_span
    s = Store(tmp_path, monkeypatch)
    path = s.write("own", _lines(_typed("/dev go"), _dispatch("toolu_1"), _dispatch("toolu_2")))
    parsed = []
    real = obligation.parse_obligation
    monkeypatch.setattr(obligation, "parse_obligation", lambda *a, **k: parsed.append(1) or real(*a, **k))
    with obligation.transcript_scan(keep=s.keep):
        span = command_span.active_span(path)
        shown = [span.dispatches(), span.obligations(), span.session_families(), span.dispatches()]
    assert len(shown[0]) == 2 and shown[0] == shown[3]
    assert len(parsed) == 2  # two prompts, four asks


# ---- the readers of a message's and a launch's result in the span (command_span: iter_calls, use_result, recorded_at)
def _launch(use_id, at="2026-11-01T10:00:00Z"):
    record = _dispatch(use_id)
    record["timestamp"] = at
    return record


def _launched(use_id, agent):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": use_id, "content": "launched"}]},
        "toolUseResult": {"isAsync": True, "status": "async_launched", "agentId": agent, "prompt": "a long prompt " * 50}}


def _message(use_id, to, at):
    return {"type": "assistant", "timestamp": at, "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": use_id, "name": "SendMessage", "input": {"to": to, "message": "go on"}}]}}


def _resumed(use_id, agent, error=False):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": use_id, "content": "ok", "is_error": error}]},
        "toolUseResult": {"resumedAgentId": agent, "success": True}}


def _asked(path, keep, ids=("toolu_1", "toolu_2", "toolu_m1", "toolu_m2", "toolu_none")):
    """What the readers of calls and results give for the span of ``path``: in a scan that keeps (keep) or one that reads whole."""
    from hooks.lib import command_span
    with obligation.transcript_scan(keep=keep) as scan:
        span = command_span.active_span(path)
        want = ("Agent", "SendMessage")
        shown = {
            "calls": [tuple(c) for c in span.iter_calls(*want)],
            "newest": [tuple(c) for c in span.iter_calls(*want, newest_first=True)],
            "before": [tuple(c) for c in span.iter_calls("SendMessage", before="toolu_m2")],
            "before_newest": [tuple(c) for c in span.iter_calls(*want, newest_first=True, before="toolu_m1")],
            "results": {i: {k: v for k, v in span.use_result(i).items() if k != "prompt" and k != "success"} for i in ids},
            "times": {i: span.recorded_at(i) for i in ids},
        }
        return shown, scan


STAGES = [
    [_typed("/dev go"), _launch("toolu_1"), _launched("toolu_1", "agent-a"), _launch("toolu_2", "2026-11-01T10:00:05Z")],
    [_message("toolu_m1", "agent-a", "2026-11-01T10:01:00Z")],
    [_resumed("toolu_m1", "agent-a"), _launched("toolu_2", "agent-b"), _message("toolu_m2", "agent-b", "2026-11-01T10:02:00Z")],
    [_resumed("toolu_m2", "agent-b", error=True)],
]


def test_the_readers_of_calls_and_results_equal_a_whole_read_after_every_addition(tmp_path, monkeypatch):
    s = Store(tmp_path, monkeypatch)
    path = s.folder / "own.jsonl"
    for stage in STAGES:
        s.write("own", _lines(*stage), "a")
        kept, _ = _asked(path, s.keep)
        whole, _ = _asked(path, None)
        assert kept == whole
    assert whole["results"]["toolu_2"]["agentId"] == "agent-b" and whole["results"]["toolu_m2"]["resumedAgentId"] == "agent-b"
    assert whole["results"]["toolu_none"] == {} and whole["times"]["toolu_m1"] == "2026-11-01T10:01:00Z"


def _reads_of_the_span(tmp_path, monkeypatch, history):
    from hooks.lib import command_span
    s = Store(tmp_path, monkeypatch)
    s.write("own", _lines(*STAGES[0], *STAGES[1]) + _chatter(history))
    path = s.folder / "own.jsonl"
    _asked(path, s.keep)
    s.write("own", _lines(*STAGES[2]) + _chatter(240), "a")
    spent = []
    real = command_span._read
    monkeypatch.setattr(command_span, "_read", lambda p: spent.append(p) or real(p))  # the span's bytes, whole
    kept, scan = _asked(path, s.keep, ids=("toolu_1", "toolu_2", "toolu_m1", "toolu_m2"))  # an id the kept reading lacks is read whole
    return kept["results"]["toolu_2"], len(spent), scan.bytes


def test_after_a_small_addition_the_span_readers_read_the_addition_only(tmp_path, monkeypatch):
    small = _reads_of_the_span(tmp_path / "a", monkeypatch, 200_000)
    large = _reads_of_the_span(tmp_path / "b", monkeypatch, 2_000_000)
    assert small == large  # the same at ten times the history
    assert large[0]["agentId"] == "agent-b" and large[1] == 0 and large[2] < 9 * transcript_index.WINDOW


def test_the_time_locks_reader_and_the_span_reader_keep_an_entry_each(tmp_path, monkeypatch):
    """timelock_released asks for the opener among two commands, the span among the harness's: one entry per set of
    commands, else each stop reads the conversation whole to replace the other's."""
    from hooks.lib import command_span
    s = Store(tmp_path, monkeypatch)
    path = s.write("own", _lines(_typed("/dev go"), _launch("toolu_1")) + _chatter(2_000_000))

    def ask():
        with obligation.transcript_scan(keep=s.keep) as scan:
            return command_span.active_span(path).command, command_span.timelock_released(path), scan.bytes
    first = ask()
    s.write("own", _chatter(240), "a")
    second = ask()
    assert first[:2] == second[:2] == ("dev", False)
    assert second[2] < 12 * transcript_index.WINDOW < first[2]  # the addition and fixed checks, not 2 MB twice


def _said(text, sidechain=False, who="assistant"):
    record = {"type": who, "message": {"role": who, "content": [{"type": "text", "text": text}]}}
    return dict(record, isSidechain=True) if sidechain else record


@pytest.mark.parametrize("tail", [[], [_said("sub says", sidechain=True)], [_said("user says", who="user")],
                                  [_said("one"), _said("two")], [_launch("toolu_9")]])
def test_the_last_text_is_the_last_of_the_texts(tmp_path, monkeypatch, tail):
    from hooks.lib import command_span
    s = Store(tmp_path, monkeypatch)
    path = s.write("own", _lines(_typed("/dev go"), _said("first"), _launch("toolu_1"), _said("second"), *tail))
    span = command_span.active_span(path)
    assert span.last_text() == (span.texts() or [""])[-1]
    empty = command_span.active_span(s.write("own", _lines(_typed("/dev go"), _launch("toolu_1"))))
    assert empty.last_text() == "" == (empty.texts() or [""])[-1]


@pytest.mark.parametrize("history", [100, 1000])
def test_the_last_text_decodes_the_newest_records_not_the_history(tmp_path, monkeypatch, history):
    from hooks.lib import command_span
    s = Store(tmp_path, monkeypatch)
    path = s.write("own", _lines(_typed("/dev go"), *[_said(f"text {i}") for i in range(history)]))
    span = command_span.active_span(path)
    decoded = []
    real = command_span._decode
    monkeypatch.setattr(command_span, "_decode", lambda raw: decoded.append(1) or real(raw))
    assert span.last_text() == f"text {history - 1}"
    assert len(decoded) == 1  # the same at 100 and 1000 records


def test_a_path_read_through_pathlib_is_a_fact_on_every_interpreter_and_the_patch_is_undone(tmp_path):
    (tmp_path / "a.txt").write_text("1")
    (tmp_path / "b.txt").write_text("2")
    before = (Path.stat, Path.open, Path.iterdir, Path.read_text)
    with fact_cache.watch() as reads:
        (tmp_path / "a.txt").read_text()
        (tmp_path / "b.txt").stat()
        list(tmp_path.iterdir())
        (tmp_path / "gone.txt").exists()
    assert {str(tmp_path / n) for n in ("a.txt", "b.txt", "gone.txt")} | {str(tmp_path)} <= reads.paths
    assert (Path.stat, Path.open, Path.iterdir, Path.read_text) == before
