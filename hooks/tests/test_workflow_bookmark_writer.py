"""The workflow bookmark has one writer (P1b goal 1, D24).

<project>/.claude/workflow-<sid>.json had three producers: prompt-workflow.py
(a command's start, and /dev's start), the Codex plan path of
pretool-workflow-gate.py (its acknowledgement and its lock) and
posttool-subagent-track.py (a subagent call recorded). All five writes now go
through lib.todo_canonical.write_bookmark, and each keeps the bytes it wrote
before. The writer replaces the file whole (a new file renamed over it), so a
handle opened on the old bookmark keeps reading the old bytes; four of the five
writes used to rewrite the file in place.

Every site test fails on the code before the one writer: either the writer is
missing, the site does not call it, or the site rewrites the file in place.

Run with: python3 -m pytest hooks/tests/test_workflow_bookmark_writer.py -v
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import locale
import os
import stat
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS))  # the hooks load their library as lib.<module>
TODO_CANONICAL = importlib.import_module("lib.todo_canonical")
assert Path(TODO_CANONICAL.__file__).resolve() == HOOKS / "lib" / "todo_canonical.py"


def _load(filename: str):
    spec = importlib.util.spec_from_file_location(
        "bookmark_writer_" + filename[:-3].replace("-", "_"), HOOKS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROMPT = _load("prompt-workflow.py")
GATE = _load("pretool-workflow-gate.py")
TRACKER = _load("posttool-subagent-track.py")
LOCALE = locale.getpreferredencoding(False)  # what Path.write_text encodes with


@pytest.fixture
def writes(monkeypatch):
    """The bookmark paths the one writer was called with, in order; each call
    then goes to the writer itself."""
    seen = []
    writer = TODO_CANONICAL.write_bookmark

    def recorded(path, update, encoding=None):
        seen.append(Path(path))
        return writer(path, update, encoding)

    monkeypatch.setattr(TODO_CANONICAL, "write_bookmark", recorded)
    # the tracker binds the name when it loads; the other two look it up at the write
    monkeypatch.setattr(TRACKER, "write_bookmark", recorded, raising=False)
    return seen


def _bookmark(tmp_path: Path, sid: str = "s1") -> Path:
    path = tmp_path / ".claude" / f"workflow-{sid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class _Held:
    """A handle opened on the bookmark before a write: a whole-file replacement
    leaves it on the old bytes, an in-place rewrite does not."""

    def __init__(self, path: Path):
        self.path = path
        self.before = path.read_bytes()
        self.inode = path.stat().st_ino
        self.handle = open(path, "rb")

    def assert_replaced(self) -> None:
        try:
            assert self.handle.read() == self.before
        finally:
            self.handle.close()
        assert self.path.stat().st_ino != self.inode
        assert not [p.name for p in self.path.parent.iterdir() if ".tmp-" in p.name]


# ---------------------------------------------------------------- the writer

def test_writer_replaces_the_file_whole(tmp_path):
    path = _bookmark(tmp_path)
    path.write_text('{"old": 1}')
    held = _Held(path)
    seen = []

    TODO_CANONICAL.write_bookmark(path, lambda text: seen.append(text) or '{"new": 2}')

    assert seen == ['{"old": 1}']
    assert path.read_bytes() == b'{"new": 2}'
    held.assert_replaced()
    assert path.stat().st_mode & 0o777 == 0o600


def test_writer_gives_none_when_nothing_is_readable(tmp_path):
    path = _bookmark(tmp_path)
    seen = []
    TODO_CANONICAL.write_bookmark(path, lambda text: seen.append(text) or "{}")
    assert seen == [None] and path.read_bytes() == b"{}"

    path.unlink()
    path.mkdir()  # a directory where the bookmark goes: not readable, not replaced
    with pytest.raises(OSError):
        TODO_CANONICAL.write_bookmark(path, lambda text: seen.append(text) or "{}")
    assert seen == [None, None] and path.is_dir()
    assert not [p.name for p in path.parent.iterdir() if ".tmp-" in p.name]


def test_writer_leaves_the_file_when_update_declines_or_raises(tmp_path):
    path = _bookmark(tmp_path)
    path.write_text('{"kept": true}')
    inode = path.stat().st_ino

    TODO_CANONICAL.write_bookmark(path, lambda text: None)
    with pytest.raises(ZeroDivisionError):
        TODO_CANONICAL.write_bookmark(path, lambda text: 1 / 0)

    assert path.read_bytes() == b'{"kept": true}' and path.stat().st_ino == inode
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]


def test_writer_encodes_as_asked_and_as_write_text_by_default(tmp_path):
    path = _bookmark(tmp_path)
    TODO_CANONICAL.write_bookmark(path, lambda text: '{"a": "é"}', encoding="utf-8")
    assert path.read_bytes() == '{"a": "é"}'.encode("utf-8")
    seen = []
    TODO_CANONICAL.write_bookmark(path, lambda text: seen.append(text) or '{"b": "é"}')
    assert seen == ['{"a": "é"}'.encode("utf-8").decode(LOCALE)]
    assert path.read_bytes() == '{"b": "é"}'.encode(LOCALE)


def _replaced_while_syncing(monkeypatch, path: Path, times: int) -> list:
    """Another hook replaces the bookmark while the writer syncs its new text,
    ``times`` times; returns the values it wrote."""
    sync, written = os.fsync, []

    def busy(fd):
        if stat.S_ISREG(os.fstat(fd).st_mode) and len(written) < times:
            written.append(len(written) + 1)
            other = path.with_name("other-hook")
            other.write_text(json.dumps({"other": written[-1]}))
            os.replace(other, path)
        sync(fd)

    monkeypatch.setattr(TODO_CANONICAL.os, "fsync", busy)
    return written


def test_writer_starts_again_from_a_bookmark_replaced_meanwhile(tmp_path, monkeypatch):
    path = _bookmark(tmp_path)
    path.write_text('{"mine": 0}')
    _replaced_while_syncing(monkeypatch, path, 1)
    seen = []

    def mark(text):
        seen.append(text)
        return json.dumps(dict(json.loads(text), mark=True))

    TODO_CANONICAL.write_bookmark(path, mark)

    # the other hook's write is kept and this one's mark lands on it
    assert seen == ['{"mine": 0}', '{"other": 1}']
    assert json.loads(path.read_text()) == {"other": 1, "mark": True}


def test_writer_publishes_after_three_reads_however_busy(tmp_path, monkeypatch):
    path = _bookmark(tmp_path)
    path.write_text('{"mine": 0}')
    _replaced_while_syncing(monkeypatch, path, 10)
    seen = []

    TODO_CANONICAL.write_bookmark(path, lambda text: seen.append(text) or json.dumps({"n": len(seen)}))

    assert seen == ['{"mine": 0}', '{"other": 1}', '{"other": 2}']
    assert json.loads(path.read_text()) == {"n": 3}
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]


def test_writer_replaces_a_link_instead_of_writing_through_it(tmp_path):
    target = tmp_path / "elsewhere.json"
    target.write_text("untouched")
    path = _bookmark(tmp_path)
    path.symlink_to(target)

    TODO_CANONICAL.write_bookmark(path, lambda text: "{}")

    assert not path.is_symlink() and path.read_bytes() == b"{}"
    assert target.read_text() == "untouched"


# ---------------------------------------------------------------- prompt-workflow.py

def test_command_start_writes_through_the_writer(tmp_path, monkeypatch, writes):
    monkeypatch.setattr(PROMPT, "PROJECT_DIR", tmp_path)
    path = _bookmark(tmp_path)
    path.write_text('{"command": "spec", "last_todos": []}')
    held = _Held(path)

    PROMPT._write_bookmark("close", "s1", "--force é")

    assert writes == [path]
    held.assert_replaced()
    raw = path.read_bytes()
    data = json.loads(raw)
    # a new workflow: nothing of the previous one is kept, the keys in the order
    # the start writes them, non-ASCII escaped (json.dumps' defaults)
    assert list(data) == ["command", "workflow_instance_id", "workflow_generation",
                          "workflow_started_at_ms", "arguments"]
    assert data["command"] == "close" and data["workflow_generation"] == 1
    assert data["arguments"] == "--force é"
    assert raw == json.dumps(data).encode("ascii")


@pytest.fixture
def dev_start(tmp_path, monkeypatch):
    """_ordinary_dev_start with the parts that do not touch the bookmark held
    still: the checklist, the conflict check, the registry and the spec."""
    monkeypatch.setattr(PROMPT, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(PROMPT, "run_todo_script",
                        lambda cmd, prompt: [{"content": "Step 0", "status": "pending", "activeForm": "Step 0"}])
    monkeypatch.setattr(PROMPT, "_check_workflow_conflict", lambda cmd: None)
    monkeypatch.setattr(PROMPT, "_init_dev_registry", lambda cmd, prompt, sid, project: "dev-20261030-000000-x")
    monkeypatch.setattr(PROMPT, "_start_identity", lambda task_id: f"Task id: {task_id}\n")
    monkeypatch.setattr(PROMPT, "decide_spec_path", lambda explicit, sid: "")

    def start(prompt: str, digest: str):
        PROMPT._ordinary_dev_start("dev", prompt, "s1", digest)
        return json.loads(PROMPT._dev_replay_path("s1", digest).read_text(encoding="utf-8"))

    return start


def test_dev_start_writes_through_the_writer(tmp_path, dev_start, writes, capsys):
    path = _bookmark(tmp_path)
    path.write_text(json.dumps({"command": "dev", "workflow_generation": 4}))
    held = _Held(path)

    replay = dev_start("/dev résumé page", "d1")

    assert writes == [path]
    held.assert_replaced()
    raw = path.read_bytes()
    data = json.loads(raw)
    assert data["workflow_generation"] == 5 == replay["workflow_generation"]
    assert data["task_id"] == "dev-20261030-000000-x" and data["start_envelope_sha256"] == "d1"
    assert data["arguments"] == "résumé page"
    # sorted keys, UTF-8, non-ASCII kept as it is: the bytes the start always wrote
    assert raw == json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    assert "Task id: dev-20261030-000000-x" in capsys.readouterr().out


@pytest.mark.parametrize("previous", [None, "", "{not json", '{"workflow_generation": 0}'])
def test_dev_start_counts_from_one_without_a_readable_generation(tmp_path, dev_start, previous):
    path = _bookmark(tmp_path)
    if previous is not None:
        path.write_text(previous)
    assert dev_start("/dev x", "d2")["workflow_generation"] == 1
    assert json.loads(path.read_text())["workflow_generation"] == 1


# ---------------------------------------------------------------- posttool-subagent-track.py

def test_subagent_call_is_recorded_through_the_writer(tmp_path, writes):
    path = _bookmark(tmp_path)
    before = {"command": "dev", "last_todos": [{"content": "ré"}], "subagent_calls": {"0": True}}
    path.write_text(json.dumps(before))
    held = _Held(path)

    TRACKER._record_subagent_call_legacy(path, "2")

    assert writes == [path]
    held.assert_replaced()
    expected = dict(before, subagent_calls={"0": True, "2": True})
    assert path.read_bytes() == json.dumps(expected).encode("ascii")


@pytest.mark.parametrize("previous", [None, "{not json", "[1, 2]", "null"])
def test_subagent_call_without_a_bookmark_writes_nothing(tmp_path, previous):
    path = _bookmark(tmp_path)
    if previous is not None:
        path.write_text(previous)
    TRACKER._record_subagent_call_legacy(path, "0")
    assert sorted(p.name for p in path.parent.iterdir()) == ([path.name] if previous is not None else [])
    if previous is not None:
        assert path.read_text() == previous


# ---------------------------------------------------------------- pretool-workflow-gate.py (Codex)

def _todos(*statuses):
    return [{"content": f"Step {i} étape", "status": s} for i, s in enumerate(statuses)]


def test_codex_acknowledgement_writes_through_the_writer(tmp_path, monkeypatch, writes):
    monkeypatch.setattr(GATE, "official_todos_path", lambda sid: tmp_path / "todos.json")
    monkeypatch.setattr(GATE.time, "time_ns", lambda: 1_700_000_000_000 * 1_000_000)
    path = _bookmark(tmp_path)
    state = {"command": "dev", "lock_reason": "not_started"}
    path.write_text(json.dumps(state))
    held = _Held(path)

    assert GATE.persist_codex_initialization("s1", path, state, _todos("in_progress", "pending"), implicit=True)

    assert writes == [path]
    held.assert_replaced()
    assert "lock_reason" not in state and state["codex_plan_acknowledged_implicit"] is True
    assert path.read_bytes() == json.dumps(state, ensure_ascii=False).encode(LOCALE)


def test_codex_acknowledgement_publishes_the_state_it_decided_on(tmp_path, monkeypatch):
    """The gate's write is the whole state its checks ran on, as before the one
    writer: what another hook wrote after the gate read the bookmark is not
    merged in (write_bookmark's docstring; the race the lane report describes)."""
    monkeypatch.setattr(GATE, "official_todos_path", lambda sid: tmp_path / "todos.json")
    path = _bookmark(tmp_path)
    state = {"command": "dev"}
    path.write_text(json.dumps({"command": "dev", "subagent_calls": {"0": True}}))

    assert GATE.persist_codex_initialization("s1", path, state, _todos("in_progress"), implicit=False)

    assert "subagent_calls" not in json.loads(path.read_text())


def test_codex_sequence_lock_writes_through_the_writer(tmp_path, monkeypatch, writes, capsys):
    monkeypatch.setenv("CLAUDE_COMPAT_RUNTIME", "codex")
    canonical = [{"content": f"Step {i} étape"} for i in range(3)]
    monkeypatch.setattr(GATE, "run_canonical_todos", lambda cmd, project, prompt="": canonical)
    path = _bookmark(tmp_path)
    path.write_text(json.dumps({"command": "dev", "todo_acknowledged": True,
                                "last_todos": _todos("in_progress", "pending", "pending")}, ensure_ascii=False))
    held = _Held(path)
    plan = [{"step": f"Step {i} étape", "status": s}
            for i, s in enumerate(("in_progress", "pending", "in_progress"))]
    data = {"tool_name": "functions.update_plan", "tool_input": {"plan": plan}, "session_id": "s1"}

    with pytest.raises(SystemExit) as stop:
        GATE.acknowledge_codex_plan(data, "s1", path, tmp_path)

    assert stop.value.code == 2 and "BLOCKED Codex update_plan for /dev" in capsys.readouterr().err
    assert writes == [path]
    held.assert_replaced()
    expected = {"command": "dev", "todo_acknowledged": False,
                "last_todos": _todos("in_progress", "pending", "pending"), "lock_reason": "sequence_violation"}
    assert path.read_bytes() == json.dumps(expected, ensure_ascii=False).encode(LOCALE)
