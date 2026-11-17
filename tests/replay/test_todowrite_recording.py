"""The replay's TodoWrite gives what the real CLI gave (tests/fixtures/cli-todowrite-oldtodos).

The recording is CLI 2.1.326's own stream-json output for two TodoWrite calls: a list whose items
are all completed, then a one-item pending list. The CLI stores [] once every item is completed, so
the second call's oldTodos is [], while each call's newTodos is its own input. The replay's
simulation (replay._default_perform) fed the same inputs in the same order yields the same
oldTodos/newTodos sequence.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tests.replay import replay

RECORDING = Path(__file__).resolve().parents[1] / "fixtures" / "cli-todowrite-oldtodos" / "stream-2.1.326.jsonl"


def _recorded() -> list:
    """(input todos, tool_use_result) of each TodoWrite call, in the order the CLI ran them."""
    inputs, pairs = {}, []
    for line in RECORDING.read_text(encoding="utf-8").splitlines():
        ev = json.loads(line)
        for block in (ev.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if ev["type"] == "assistant" and block.get("type") == "tool_use" and block.get("name") == "TodoWrite":
                inputs[block["id"]] = block["input"]["todos"]
            elif ev["type"] == "user" and block.get("type") == "tool_result" and block.get("tool_use_id") in inputs:
                pairs.append((inputs[block["tool_use_id"]], ev["tool_use_result"]))
    return pairs


def test_recording_holds_the_all_completed_case():
    calls = _recorded()
    assert len(calls) == 2
    assert all(t["status"] == "completed" for t in calls[0][0])
    assert calls[1][1]["oldTodos"] == []


def test_replay_todowrite_matches_the_recording(tmp_path):
    session = SimpleNamespace(rp=SimpleNamespace(layout=SimpleNamespace(project=str(tmp_path))))
    actor = replay.Actor(session, None)
    for todos, recorded in _recorded():
        got = replay._default_perform(actor, "TodoWrite", {"todos": json.loads(json.dumps(todos))})()
        assert got == recorded
