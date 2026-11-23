"""E1's differential re-runs a PreToolUse Write with the Write's own new file absent, as at its event.

The differential runs every unit on the replay's final state. A Write that created its file (the trace's
first event on the path is that Write's own create) left the file there, so a hook that refuses a Write
onto an existing file (hooks/lib/write_gate/overwrite.py) refused the re-run, which the event never saw:
the unit was "reproduced False" and never measured (the merge-analyst's grant, unit #29 of merge~*).
The re-run that cuts the transcripts back to the event now also removes that file; a file that existed
before the event (no create of it by that event) stays, so the same hook still refuses there.

It needs a mount namespace (root, as tests/replay/test_run_to_run.py); without one it fails with the
reason, never skips.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests.replay import differential as D

HOOK = '''import json, os, sys
p = json.load(sys.stdin)["tool_input"]["file_path"]
sys.exit(2 if os.path.exists(p) else 0)
'''


def _require():
    p = subprocess.run(["unshare", "--mount", "--pid", "--fork", "true"], capture_output=True, text=True)
    if p.returncode != 0:
        pytest.fail("the differential needs a mount namespace: " + p.stderr.strip(), pytrace=False)


def _work(tmp, created_by_the_event: bool) -> str:
    sb = os.path.join(tmp, "sb")
    lay = {k: os.path.join(sb, k) for k in ("home", "state", "project")}
    for d in lay.values():
        os.makedirs(d)
    with open(os.path.join(sb, "hook.py"), "w") as fh:
        fh.write(HOOK)
    target = os.path.join(lay["state"], "grant.json")
    with open(target, "w") as fh:  # the final state: the Write's file is there
        fh.write("{}")
    work = os.path.join(sb, "differential")
    os.makedirs(work)
    unit = {"seq": 3, "origin": "hooks/toy-overwrite-gate.py", "kind": "hook", "event": "PreToolUse",
            "tool": "Write", "command": f"{sys.executable} {os.path.join(sb, 'hook.py')}",
            "original": [0, "ok", ""], "reads": []}
    payload = {"tool_name": "Write", "tool_input": {"file_path": target, "content": "{}"},
               "hook_event_name": "PreToolUse"}
    inv = {"seq": 3, "event": "PreToolUse", "payload": payload, "transcripts": {}}
    for name, data in (("env.json", {"PATH": "/usr/bin:/bin"}), ("bash-env.json", {"PATH": "/usr/bin:/bin"})):
        with open(os.path.join(work, name), "w") as fh:
            json.dump(data, fh)
    with open(os.path.join(work, "invocations.jsonl"), "w") as fh:
        fh.write(json.dumps(inv) + "\n")
    # the trace: the Write's own create at its event, or a file an earlier event wrote
    op, event = ("create", 3) if created_by_the_event else ("create", 1)
    with open(os.path.join(work, "relation-events.tsv"), "w") as fh:
        fh.write("\t".join(["agent:toy", "", "agent:toy", op, "<state>/grant.json", str(event), "", target]) + "\n")
    path = os.path.join(work, "units.json")
    with open(path, "w") as fh:
        json.dump({"units": [unit], "schemas": {}, "workers": 1,
                   "layout": dict(lay, sb=sb, temp_dirs=[])}, fh)
    return path


def _result(units_path: str) -> dict:
    assert D._inner(units_path) == 0
    with open(os.path.join(os.path.dirname(units_path), "results.json")) as fh:
        return json.load(fh)["units"][0]


def test_a_write_is_re_run_without_the_file_it_created(tmp_path):
    _require()
    rec = _result(_work(str(tmp_path), True))
    assert rec["reproduced"], rec
    assert rec["intact"] == [0, "ok", ""], rec
    assert os.path.exists(os.path.join(str(tmp_path), "sb", "state", "grant.json"))  # the final state is kept


def test_a_file_that_was_there_before_the_write_stays(tmp_path):
    _require()
    rec = _result(_work(str(tmp_path), False))
    assert not rec["reproduced"], rec


def test_a_run_cut_by_its_time_limit_ends_the_differential_naming_the_unit(monkeypatch, tmp_path):
    """A hook that exceeds its limit is no measurement (its verdict would depend on the machine's speed)."""
    def cut(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])
    monkeypatch.setattr(D.subprocess, "run", cut)
    lay = {k: str(tmp_path / k) for k in ("home", "state", "project")}
    unit = {"seq": 7, "origin": "hooks/toy-slow.py", "kind": "hook", "event": "Stop", "command": "true",
            "timeout": 1, "original": [0, "ok", ""], "reads": []}
    with pytest.raises(RuntimeError) as e:
        D._one({"layout": dict(lay, sb=str(tmp_path), temp_dirs=[])}, 0, unit, None, "{}", {})
    msg = str(e.value)
    assert "hooks/toy-slow.py" in msg and "Stop" in msg and "seq 7" in msg and "limit 10 s" in msg, msg
