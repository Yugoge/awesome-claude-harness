#!/usr/bin/env python3
"""A3.a (hooks/subagentstop-artifact-contract-enforce.py, _file_lists_errors) judges a dev by what THIS dispatch
declared: the entries its report already held when the dispatch began (an earlier round's files, a test-writer's)
are not its own. The baseline is the lane record's (hooks/lib/lane_ledger.py): its first recorded call keeps the
report as the dispatch found it, and the record lives until the dispatch's stop stands (the gate's witness rule
lib.lane_ledger:end), so a refused stop and the next one are judged against the same baseline.

Also the shapes of the stops that were real omissions: a file this agent wrote by Edit and did not list is completed
by the record before G2 runs; a file an earlier dispatch of the lane wrote, missing from the lane's report, is named
by the block until it is listed, and no block repeats once the lane did what it named.

Every record is written by lane_ledger.record itself, from the PreToolUse payload a dev's call carries."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from test_g2_file_lists import Cycle, _blocked, _clean, _git, base  # noqa: E402  (hooks/tests on sys.path)

HOOKS = base.REPO_ROOT / "hooks"
GATE = HOOKS / "subagentstop-producer-gate.py"
sys.path.insert(0, str(HOOKS))
from lib import lane_ledger  # noqa: E402

EARLIER = ["src/r1_model.py", "src/r1_view.py", "tests/generated/test_r1.py"]  # an earlier round's, a test-writer's


@pytest.fixture
def state(tmp_path, monkeypatch):
    """The state directory the record and the hooks share, as on one machine."""
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path / "state"))
    return tmp_path / "state"


def _env(monkeypatch, c: Cycle) -> None:
    monkeypatch.setenv("HOME", str(c.home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(c.home / ".claude"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(c.project))


def _pre(c: Cycle, d: dict, tool: str, **tool_input) -> None:
    """The PreToolUse record of one of the dev's calls (hooks/pretool-lane-ledger.py's payload)."""
    lane_ledger.record({"session_id": d["session"], "agent_id": d["agent_id"], "agent_type": "dev",
                        "tool_name": tool, "tool_use_id": f"tu-{tool}", "cwd": str(c.project),
                        "transcript_path": str(c.store / f"{d['session']}.jsonl"), "tool_input": tool_input})


def _earlier_round(c: Cycle, d: dict) -> None:
    """The lane report as the dispatch finds it: an earlier round's files, written then and not by this agent."""
    for rel in EARLIER:
        base._write(c.project / rel, f"# {rel}\n")
    report = base._l2_dev_report(d["task"], lane=d["lane"], lane_set=d["lane_set"])
    report["owned_edits"], report["pre_edit_snapshots"] = {}, {}
    report["dev"].update(files_modified=[], files_created=list(EARLIER))
    base._write(c.project / d["report"], report)


def _lane(c: Cycle, monkeypatch, agent: str = "agent-laner") -> dict:
    """A fan-out lane re-dispatched onto its report: it edits src/app.py; its record is taken before the edit."""
    _env(monkeypatch, c)
    edit = {"file_path": c.path("src/app.py"), "old_string": "x = 1\n", "new_string": "x = 2\n"}
    d = c.dispatch("session-fan", agent, [("Edit", edit, True)], lane="r05", lane_set=["r04", "r05"])
    _earlier_round(c, d)
    _pre(c, d, "Edit", **edit)
    base._write(c.project / "src/app.py", "x = 2\n")
    return d


def test_entries_the_report_held_at_dispatch_start_are_not_this_dispatchs(tmp_path, state, monkeypatch):
    c = Cycle(tmp_path)
    d = _lane(c, monkeypatch)
    _clean(c.stop(d, ["src/app.py"], EARLIER))


def test_a_path_this_dispatch_added_and_never_wrote_blocks_until_it_is_dropped(tmp_path, state, monkeypatch):
    """Only the dispatch's own claim is named; the same stop repeats while it stays, and passes once dropped."""
    c = Cycle(tmp_path)
    d = _lane(c, monkeypatch)
    for _ in range(2):  # a refused stop keeps the record: the second stop has the same baseline, the same block
        _blocked(c.stop(d, ["src/app.py", "src/ghost.py"], EARLIER), d["report"], "src/ghost.py", "(none)",
                 f"files_modified: src/app.py; files_created: {', '.join(EARLIER)}")
    _clean(c.stop(d, ["src/app.py"], EARLIER))


def test_without_a_baseline_every_entry_is_judged(tmp_path, state, monkeypatch):
    """No record of this dispatch (a lane that recorded no call): nothing is taken as an earlier round's."""
    c = Cycle(tmp_path)
    _env(monkeypatch, c)
    d = c.dispatch("session-fan", "agent-norecord", [], lane="r05", lane_set=["r04", "r05"])
    _earlier_round(c, d)
    proc = c.stop(d, [], EARLIER)
    assert proc.returncode == 2 and "declared but not written by this dev: " + ", ".join(EARLIER) in proc.stderr


def _gate(c: Cycle, d: dict) -> subprocess.CompletedProcess:
    return base._run_hook(c.project, c.home, d["agent_id"], session_id=d["session"], stopgate_mode="block",
                          hook_path=GATE, extra_payload={"agent_type": "dev", "agent_transcript_path": d["transcript"]})


def _write_report(c: Cycle, d: dict, modified, created) -> None:
    report = json.loads((c.project / d["report"]).read_text())
    report["dev"].update(files_modified=list(modified), files_created=list(created))
    base._write(c.project / d["report"], report)


def test_a_refused_stop_keeps_the_record_and_the_stop_that_stands_removes_it(tmp_path, state, monkeypatch):
    c = Cycle(tmp_path)
    d = _lane(c, monkeypatch)
    record = lane_ledger._path(d["session"], d["agent_id"])
    _write_report(c, d, ["src/app.py", "src/ghost.py"], EARLIER)
    refused = _gate(c, d)
    assert refused.returncode == 2 and "declared but not written by this dev: src/ghost.py\n" in refused.stderr
    assert record.is_file()
    _write_report(c, d, ["src/app.py"], EARLIER)  # what the block named
    stood = _gate(c, d)
    assert stood.returncode == 0, stood.stderr
    assert not record.exists() and not record.with_suffix(".lock").exists()


def _single(c: Cycle, monkeypatch, agent: str, calls) -> dict:
    _env(monkeypatch, c)
    d = c.dispatch("session-one", agent, calls)
    report = base._l2_dev_report(d["task"])
    report["owned_edits"], report["pre_edit_snapshots"] = {}, {}
    report["dev"].update(files_modified=[], files_created=[])  # the lane listed nothing it wrote
    base._write(c.project / d["report"], report)
    return d


def test_a_file_written_by_edit_in_another_tree_and_not_listed_is_completed(tmp_path, state, monkeypatch):
    """The recorded stop of a lane that edited a file of another work tree by absolute path and left it out."""
    c = Cycle(tmp_path)
    other = tmp_path / "release"
    other.mkdir()
    _git(other, "init", "-q", "-b", "main")
    _git(other, "config", "user.email", "t@example.invalid")
    _git(other, "config", "user.name", "t")
    base._write(other / "ui" / "Drawer.tsx", "old\n")
    _git(other, "add", ".")
    _git(other, "commit", "-q", "-m", "seed")
    edit = {"file_path": str(other / "ui" / "Drawer.tsx"), "old_string": "old\n", "new_string": "new\n"}
    d = _single(c, monkeypatch, "agent-edited", [("Edit", edit, True)])
    _pre(c, d, "Edit", **edit)
    base._write(other / "ui" / "Drawer.tsx", "new\n")
    # /commit's planner refuses a path outside the project's repositories (its own finding, kept); A3.a is satisfied
    for n in range(2):  # a stop again: the file-lists block does not come back
        proc = _gate(c, d)
        assert "file_lists_differ" not in proc.stderr and ("lane-ledger: your report was completed" in proc.stderr) == (
            n == 0), proc.stderr
    assert json.loads((c.project / d["report"]).read_text())["dev"]["files_modified"] == [str(other / "ui/Drawer.tsx")]


def test_an_earlier_dispatchs_write_missing_from_the_lane_report_blocks_until_listed(tmp_path, state, monkeypatch):
    """The other recorded omissions: an earlier dispatch of the same lane wrote the file (Write), the lane's report no
    longer lists it, and this dispatch never touched it. This agent's record cannot hold it, so nothing completes
    it: the block names it, repeats while it is missing, and passes once it is listed."""
    c = Cycle(tmp_path)
    _env(monkeypatch, c)
    lane = {"lane": "r02", "lane_set": ["r01", "r02"]}
    base._write(c.project / "src/r02_round1.py", "r = 1\n")
    c.dispatch("session-fan", "agent-round1",
               [("Write", {"file_path": c.path("src/r02_round1.py"), "content": "r = 1\n"}, True)], **lane)
    edit = {"file_path": c.path("src/app.py"), "old_string": "x = 1\n", "new_string": "x = 2\n"}
    d = c.dispatch("session-fan", "agent-round2", [("Edit", edit, True)], **lane)
    _pre(c, d, "Edit", **edit)
    base._write(c.project / "src/app.py", "x = 2\n")
    for _ in range(2):
        _blocked(c.stop(d, ["src/app.py"], []), d["report"], "(none)", "src/r02_round1.py",
                 "files_modified: src/app.py; files_created: src/r02_round1.py")
    for _ in range(2):  # done what the block named: no repeat
        _clean(c.stop(d, ["src/app.py"], ["src/r02_round1.py"]))
