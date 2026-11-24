"""The Stop gate's scan reads a saved conversation that has grown from where it stopped (lib/transcript_index).

1. A grown conversation (a continuation) gives the records a whole read gives, whatever was added: whole lines,
   an unfinished last line, a dispatch refused by a hook; one that is no continuation (shorter, or changed before
   the point read) is read whole again, and gives the same records too.
2. What a stop reads is counted, never timed: after a small addition it is the addition and a fixed check,
   the same at two sizes of conversation.
3. A scan that is cut off keeps what it has read.
Conversations are made up here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from hooks.lib import obligation, transcript_index  # noqa: E402
from hooks.lib.subagent_restart import project_slug  # noqa: E402

TASK = "20261101-100000"
OTHER = "20261101-110000"


def _doc(task, role, at):
    return {"task_id": task, "lane": None, "lane_set": None, "role": role, "pipeline": "dev", "profile": "singular",
            "dispatched_at": at,
            "artifacts": [{"kind": "json", "path": f"docs/dev/context-{task}.json", "schema": "context.v1",
                           "identity": {"task_id": task}}]}


def _dispatch(use_id, task, role="ba"):
    prompt = "FIRST ACTION: register.\n" + obligation.serialize_obligation(_doc(task, role, "2026-11-01T10:00:00Z"))
    return {"type": "assistant", "timestamp": "2026-11-01T10:00:00Z", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": use_id, "name": "Agent", "input": {"subagent_type": role, "prompt": prompt}}]}}


def _refused(use_id):
    return {"type": "user", "permissionDecision": {"decision": "reject", "source": "hook"},
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": use_id, "content": "no"}]}}


def _typed(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _filler(size):
    """Lines of made-up chatter of about ``size`` bytes."""
    line = json.dumps({"type": "user", "message": {"role": "user", "content": "chatter " * 12}}) + "\n"
    return line * max(1, size // len(line))


def _lines(*records):
    return "".join(json.dumps(r) + "\n" for r in records)


class Store:
    def __init__(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir(parents=True)
        self.project = tmp_path / "proj"
        self.project.mkdir()
        self.root = tmp_path / "projects"
        self.folder = self.root / project_slug(self.project)
        self.folder.mkdir(parents=True)
        self.keep = tmp_path / "state"

    def write(self, name, text, mode="w"):
        path = self.folder / f"{name}.jsonl"
        with open(path, mode, encoding="utf-8") as handle:
            handle.write(text)
        return path

    def ask(self, keep=True, task=TASK):
        """(the task's records, the scan) of one scan."""
        with obligation.transcript_scan(keep=self.keep if keep else None) as scan:
            records = obligation._task_records(task, self.project, [self.root])
            other = obligation._task_records(OTHER, self.project, [self.root])
            return (records, other), scan


def _same_as_whole(store):
    """The records of a scan that keeps its readings, equal to those of a scan that reads every file whole."""
    kept, scan = store.ask(keep=True)
    whole, _ = store.ask(keep=False)
    assert kept == whole
    return kept, scan


def test_a_grown_conversation_gives_the_records_a_whole_read_gives(tmp_path, monkeypatch):
    store = Store(tmp_path, monkeypatch)
    live = store.write("live", _lines(_typed("/dev build it"), _dispatch("t1", TASK), _dispatch("o1", OTHER)))
    store.write("older", _lines(_typed("/dev older"), _dispatch("t2", TASK, "qa")))
    first, _ = _same_as_whole(store)
    assert sorted(r["tool_use_id"] for r in first[0]) == ["t1", "t2"] and [r["tool_use_id"] for r in first[1]] == ["o1"]
    assert first[0][0]["span"] is not None
    store.write("live", _lines(_dispatch("t3", TASK, "dev"), _refused("t1")), "a")  # whole lines, a refusal
    grown, _ = _same_as_whole(store)
    assert "t3" in {r["tool_use_id"] for r in grown[0]} and "t1" not in {r["tool_use_id"] for r in grown[0]}
    half = json.dumps(_dispatch("t4", TASK, "qa"))
    store.write("live", half[:60], "a")  # an unfinished last line: a whole read takes it as it is
    _same_as_whole(store)
    store.write("live", half[60:] + "\n", "a")  # and when the line is finished
    finished, _ = _same_as_whole(store)
    assert "t4" in {r["tool_use_id"] for r in finished[0]}
    assert live.stat().st_size > 0


@pytest.mark.parametrize("change", ["shorter", "changed_before", "replaced"])
def test_a_file_that_is_no_continuation_is_read_whole_again(tmp_path, monkeypatch, change):
    store = Store(tmp_path, monkeypatch)
    body = _lines(_typed("/dev go"), _dispatch("t1", TASK)) + _filler(200_000) + _lines(_dispatch("t2", TASK, "qa"))
    path = store.write("live", body)
    _same_as_whole(store)
    if change == "shorter":
        store.write("live", body[:len(body) // 2])
    elif change == "changed_before":  # same size, an early byte different: the first dispatch is another task's
        store.write("live", body.replace(TASK, OTHER, 1))
    else:
        store.write("live", _lines(_typed("/dev other"), _dispatch("n1", TASK, "dev")) + _filler(300_000))
    assert path.stat().st_size > 0
    after, scan = _same_as_whole(store)
    assert scan.bytes >= path.stat().st_size  # read whole, not from the old offset
    assert {r["tool_use_id"] for r in after[0]} <= {"t1", "t2", "n1"}


def _reads_after_a_small_addition(tmp_path, monkeypatch, size):
    store = Store(tmp_path, monkeypatch)
    for n in range(3):  # several conversations, each naming the task
        store.write(f"s{n}", _lines(_typed("/dev go"), _dispatch(f"t{n}", TASK)) + _filler(size))
    _same_as_whole(store)
    _, warm = store.ask()
    unchanged = warm.bytes
    addition = _lines(_dispatch("tx", TASK, "qa"), _typed("noted"))
    store.write("s0", addition, "a")
    after, scan = _same_as_whole(store)
    assert "tx" in {r["tool_use_id"] for r in after[0]}
    return unchanged, scan.bytes, len(addition)


def test_a_stop_after_a_small_addition_reads_the_addition_not_the_history(tmp_path, monkeypatch):
    small = _reads_after_a_small_addition(tmp_path / "a", monkeypatch, 1_000_000)
    large = _reads_after_a_small_addition(tmp_path / "b", monkeypatch, 5_000_000)  # five times the size
    assert small[1] - small[2] == large[1] - large[2]  # the same fixed check, whatever the history's size
    assert large[1] < 3 * 5_000_000 // 10  # a tenth of the history of the three conversations
    assert large[0] == small[0]  # nothing added: the same check only


def test_a_cut_off_scan_keeps_what_it_has_read(tmp_path, monkeypatch):
    store = Store(tmp_path, monkeypatch)
    size = 600_000
    for n in range(4):
        store.write(f"s{n}", _lines(_typed("/dev go"), _dispatch(f"t{n}", TASK)) + _filler(size))
    _, whole = store.ask()  # cold, for the figure
    for entry in (store.keep / transcript_index.DIR).glob("*.json"):
        entry.unlink()

    class Cut(BaseException):
        pass

    def cut(scan):
        if scan.transcripts >= 3:
            raise Cut()

    with pytest.raises(Cut):
        with obligation.transcript_scan(on_read=cut, keep=store.keep):
            obligation._task_records(TASK, store.project, [store.root])
    _, resumed = store.ask()
    assert resumed.bytes <= whole.bytes - 3 * size + 8 * transcript_index.WINDOW


def test_a_kept_entry_that_does_not_fit_is_read_whole_and_gives_the_same_records(tmp_path, monkeypatch):
    store = Store(tmp_path, monkeypatch)
    store.write("live", _lines(_typed("/dev go"), _dispatch("t1", TASK), _dispatch("o1", OTHER)))
    _same_as_whole(store)
    for entry in (store.keep / transcript_index.DIR).glob("*.json"):
        doc = json.loads(entry.read_text())
        doc["state"] = {"calls": {"x": 1}, "refused": 7, "openers": "no"} if isinstance(doc["state"], dict) else 5
        entry.write_text(json.dumps(doc))
    after, _ = _same_as_whole(store)
    assert [r["tool_use_id"] for r in after[0]] == ["t1"]
