"""E1's differential changes the record of the subagent the hook run belongs to, never one picked by a name.

An artifact pattern may cover one file per subagent (the CLI's record of each: subagents/agent-<id>.meta.json).
The replays give subagents random ids, so a pick by how the names sort made the measurement a matter of chance:
two replays of one driver measured different files, and a register of accepted reads calibrated on one did not
fit the next. Now a hook run of a subagent (its payload carries an agent_id) that read that subagent's own
record changes that record; any other run changes every file of the pattern it read, each in a run of its own.

Two recorded sessions that differ only in their subagents' ids give the same units, runs and (as the runs are
the same) verdicts. No mount namespace is needed: this reads the recorded trace only (candidates()).
"""
from __future__ import annotations

import json
import os
import re

from tests.replay import differential as D

PATTERN = "<harness>/projects/<slug>/<sid>/subagents/agent-<agent>.meta.json"
STORE = "/sbx/home/projects/-proj/0000/subagents"
GATE = 'python "$HOME/.claude/hooks/toy-gate.py"'


def _raw(aid: str) -> str:
    return f"{STORE}/agent-{aid}.meta.json"


def _session(tmp: str, ids: tuple, own: int) -> str:
    """A trace: the CLI creates one record per subagent (event 1); the toy gate reads all of them at event 5
    as the subagent ids[own] (a PreToolUse Bash) and at event 7 as the main agent; a stop gate at event 9
    reads only the stopping subagent's record. `ids` are the subagents' ids in creation order."""
    os.makedirs(tmp, exist_ok=True)
    rows = [["cli", "", "", "create", PATTERN, "1", "", _raw(a)] for a in ids]
    rows += [["hooks/toy-gate.py", "hooks/toy-gate.py", "", "read", PATTERN, str(seq), "", _raw(a)]
             for seq in (5, 7) for a in ids]
    rows += [["hooks/toy-stop.py", "hooks/toy-stop.py", "", "read", PATTERN, "9", "", _raw(ids[own])]]
    with open(os.path.join(tmp, "relation-events.tsv"), "w") as fh:
        fh.write("".join("\t".join(r) + "\n" for r in rows))

    def inv(seq, event, payload, command):
        return {"seq": seq, "event": event, "label": f"{event} {seq}", "payload": payload, "transcripts": {},
                "hooks": [{"hook": D.hookrun.hook_name(command), "command": command, "timeout": 10,
                           "rc": 0, "verdict": "ok", "how": ""}]}
    recs = [inv(1, "SessionStart", {"source": "startup"}, GATE),
            inv(5, "PreToolUse", {"tool_name": "Bash", "agent_id": ids[own], "agent_type": "cleaner",
                                  "tool_input": {"command": "true"}}, GATE),
            inv(7, "PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "true"}}, GATE),
            inv(9, "SubagentStop", {"agent_id": ids[own], "agent_type": "cleaner"}, 'python "$HOME/.claude/hooks/toy-stop.py"')]
    with open(os.path.join(tmp, "invocations.jsonl"), "w") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in recs))
    return tmp


def _masked(units: list, ids: tuple) -> list:
    """The units with each subagent id replaced by its position among `ids` (creation order), as a sorted
    structure: what stays when only the names differ."""
    text = json.dumps(units, sort_keys=True)
    for i, a in enumerate(ids):
        text = text.replace(a, f"<agent{i}>")
    out = json.loads(text)
    for u in out:
        u["reads"].sort(key=lambda r: json.dumps(r, sort_keys=True))
    return sorted(out, key=lambda u: (u["seq"], u["origin"]))


def _changed(units: list, seq: int) -> set:
    """The files (raw name stem) the unit at `seq` changes."""
    return {re.search(r"agent-([0-9a-z]+)", r["raw"]).group(1) for u in units if u["seq"] == seq for r in u["reads"]}


def test_the_pick_does_not_depend_on_the_names(tmp_path):
    names = tuple("a%016x" % n for n in (0x4444, 0x2222, 0x9999, 0x1111, 0x7777))   # creation order; the one at 2 sorts last
    other = tuple("a%016x" % n for n in (0x1111, 0x7777, 0x3333, 0x8888, 0x2222))  # other ids; the one at 2 sorts in the middle
    one = D.candidates(_session(str(tmp_path / "one"), names, 2))
    two = D.candidates(_session(str(tmp_path / "two"), other, 2))
    assert _masked(one, names) == _masked(two, other)
    assert D.run_count(one) == D.run_count(two)


def test_a_subagents_run_changes_its_own_record_only(tmp_path):
    ids = tuple("a%016x" % n for n in (0x4444, 0x2222, 0x9999, 0x1111, 0x7777))
    for own in range(len(ids)):
        units = D.candidates(_session(str(tmp_path / f"s{own}"), ids, own))
        assert _changed(units, 5) == {ids[own]}, (own, _changed(units, 5))
        assert _changed(units, 9) == {ids[own]}


def test_a_run_without_an_instance_of_its_own_changes_every_instance(tmp_path):
    ids = tuple("a%016x" % n for n in (0x4444, 0x2222, 0x9999, 0x1111, 0x7777))
    units = D.candidates(_session(str(tmp_path), ids, 1))
    assert _changed(units, 7) == set(ids)
    # per unit one intact run and two mutations of each file it changes: the gate as the subagent (1 file) 3,
    # the gate as the main agent (5 files) 11, the stop gate (1 file) 3
    assert D.run_count(units) == 3 + 11 + 3
