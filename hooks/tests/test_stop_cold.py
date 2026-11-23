"""The Stop gate's reading of the saved conversations does not multiply with the cycle's task names, and what it
keeps does not depend on its own refusals.

1. One stop reads each saved conversation once for every task name (lib/obligation transcript_scan, opened by the
   gate's main on the copy of the module the chain script uses): the work is counted, never timed.
2. A stop the limit cuts off keeps what it computed, and the next one goes on from there: the refusal record is
   appended by every block (the cut-off stop's own included), so its bytes are no fact of a kept result; what a
   result asked of it (the refused ids of a session) is.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
sys.path.insert(0, str(REPO))

from hooks.lib import obligation  # noqa: E402
from hooks.lib.subagent_restart import project_slug  # noqa: E402

FAMILIES = [f"20261101-1{n:05d}" for n in range(17)]  # a cycle and its lanes, as made-up names
TRANSCRIPTS = 5


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load(HOOKS / "stop-command-gate.py", "stop_command_gate_cold_under_test")


def _store(tmp_path: Path) -> tuple[Path, Path]:
    """A project and an account root holding TRANSCRIPTS conversations, each naming every family."""
    project = tmp_path / "project"
    project.mkdir()
    root = tmp_path / "account"
    folder = root / project_slug(project)
    folder.mkdir(parents=True)
    for n in range(TRANSCRIPTS):
        lines = [json.dumps({"type": "user", "message": {"role": "user", "content": f"filler {i} " * 20}})
                 for i in range(200)]
        lines += [json.dumps({"type": "user", "message": {"role": "user", "content": f"task {family} noted"}})
                  for family in FAMILIES]
        (folder / f"session-{n}.jsonl").write_text("\n".join(lines) + "\n")
    return project, root


@pytest.fixture
def counted(monkeypatch):
    """How many times each conversation is read whole (its bytes indexed, its lines parsed)."""
    reads = {"indexed": [], "parsed": []}
    real_runs, real_parse = obligation._id_runs, obligation._read_parent_calls
    monkeypatch.setattr(obligation, "_id_runs", lambda data: reads["indexed"].append(len(data)) or real_runs(data))
    monkeypatch.setattr(obligation, "_read_parent_calls",
                        lambda path: reads["parsed"].append(str(path)) or real_parse(path))
    return reads


def test_a_stop_reads_each_conversation_once_for_all_task_names(tmp_path, counted):
    project, root = _store(tmp_path)
    with obligation.transcript_scan():
        for family in FAMILIES:
            obligation._task_records(family, project, [root])
            obligation._task_records(family, project, [root])  # a second ask of one name reads nothing either
    assert len(counted["indexed"]) == TRANSCRIPTS
    assert sorted(counted["parsed"]) == sorted(set(counted["parsed"]))  # each parsed at most once
    assert len(counted["parsed"]) == TRANSCRIPTS


def test_without_a_scan_each_name_reads_the_conversations_again(tmp_path, counted):
    """The control: the count above is the scan's, not an accident of the store."""
    project, root = _store(tmp_path)
    for family in FAMILIES[:3]:
        obligation._task_records(family, project, [root])
    assert len(counted["parsed"]) == 3 * TRANSCRIPTS


def test_the_gate_opens_one_scan_on_the_chains_copy_of_the_module_around_all_its_tasks(monkeypatch):
    """The chain script imports hooks.lib.obligation; the gate's own import is lib.obligation: a scan on the
    gate's copy would never be seen by the chain, and each task would open its own."""
    chain = gate._script("scripts/resolve-dev-artifact-chain.py")
    seen = []
    span = types.SimpleNamespace(command="dev", args="", transcript_path="", session_families=lambda: set())
    monkeypatch.setattr(gate.command_span, "active_span", lambda transcript: span)
    monkeypatch.setattr(gate, "_lib_round", lambda: types.SimpleNamespace(runs_round=lambda span: False))
    monkeypatch.setattr(gate, "time_lock", lambda payload, span: (0, "", None))
    monkeypatch.setattr(gate, "refused_step", lambda span: None)
    monkeypatch.setattr(gate, "environment_refusal", lambda span, root: None)
    monkeypatch.setattr(gate, "analyst_refused", lambda span: None)
    monkeypatch.setattr(gate, "no_target_end", lambda span, root: False)
    monkeypatch.setattr(gate, "step_refused_end", lambda span, refused: False)
    monkeypatch.setattr(gate, "no_owner_end", lambda span, root: False)
    monkeypatch.setattr(gate, "environment_end", lambda span, env: False)
    monkeypatch.setattr(gate, "analyst_refused_end", lambda span, analyst: False)
    monkeypatch.setattr(gate, "code_close_end", lambda span, root: False)
    monkeypatch.setattr(gate, "todo_gaps", lambda span: [])
    monkeypatch.setattr(gate, "children", lambda span: ([], []))
    monkeypatch.setitem(gate.PREDICATES, "dev", lambda span, root, payload: seen.append(
        chain._harness_lib("obligation")._SCAN is not None) or [])
    assert gate.decision({"transcript_path": "x", "cwd": "."}, "block")[0] == 0
    assert seen == [True]
    assert chain._harness_lib("obligation")._SCAN is None  # and closed after


# ------------------------------------------------------------------ 2. a cut-off stop's progress holds
SESSION = "cold-session"


def _refuse(home: Path, session: str, tool_use_id: str) -> None:
    folder = Path(os.path.dirname(gate.command_span._refusal_record_files()[0]))
    folder.mkdir(parents=True, exist_ok=True)
    day = next(iter(sorted(folder.glob("refusals-*.jsonl"))), folder / "refusals-2026-11-22.jsonl")
    with day.open("a") as handle:
        handle.write(json.dumps({"kind": "refusal", "event": "PreToolUse", "session": session,
                                 "tool_use_id": tool_use_id}) + "\n")


@pytest.fixture
def kept(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    root = tmp_path / "project"
    (root / "docs" / "dev").mkdir(parents=True)
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(state))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    calls = []

    def lines(project, task, stage):
        calls.append(task)
        refused = sorted(gate.command_span.recorded_refusals(SESSION))
        return [f"GAP {task} {stage} refused={refused}"]

    monkeypatch.setitem(gate._SCRIPTS, "scripts/resolve-dev-artifact-chain.py",
                        types.SimpleNamespace(disposition_lines=lines))
    monkeypatch.setitem(gate._SCRIPTS, "scripts/aggregate-dev-report.py",
                        types.SimpleNamespace(rebuild_if_stale=lambda project, task: []))
    return root, home, calls


def test_a_block_appended_to_the_refusal_record_does_not_discard_what_was_kept(kept):
    root, home, calls = kept
    first = gate.disposition(root, "T1", "dev")
    _refuse(home, "another-session", "toolu_1")  # what every block, this gate's own included, appends
    _refuse(home, "another-session", "toolu_2")
    assert gate.disposition(root, "T1", "dev") == first
    assert calls == ["T1"]


def test_a_refusal_of_the_session_a_result_asked_about_computes_it_again(kept):
    root, home, calls = kept
    first = gate.disposition(root, "T1", "dev")
    _refuse(home, SESSION, "toolu_3")
    again = gate.disposition(root, "T1", "dev")
    assert calls == ["T1", "T1"] and again != first and "toolu_3" in again[0]
    assert gate.disposition(root, "T1", "dev") == again and calls == ["T1", "T1"]


def test_consecutive_cut_off_stops_converge_whatever_each_one_appends(kept, monkeypatch):
    root, home, calls = kept
    tasks = ["T1", "T2", "T3", "T4", "T5", "T6"]
    real = gate._SCRIPTS["scripts/resolve-dev-artifact-chain.py"].disposition_lines

    class Cut(BaseException):
        pass

    budget = {"left": 2}

    def limited(project, task, stage):
        if budget["left"] == 0:
            raise Cut()
        budget["left"] -= 1
        return real(project, task, stage)

    monkeypatch.setitem(gate._SCRIPTS, "scripts/resolve-dev-artifact-chain.py",
                        types.SimpleNamespace(disposition_lines=limited))
    verdict = None
    for attempt in range(1, 8):
        budget["left"] = 2
        try:
            verdict = [g for t in tasks for g in gate.disposition(root, t, "dev")]
            break
        except Cut:
            _refuse(home, "another-session", f"toolu_cut{attempt}")  # the cut-off stop's own block is recorded
    assert verdict is not None and len(verdict) == len(tasks)
    assert attempt == 3 and calls == tasks
