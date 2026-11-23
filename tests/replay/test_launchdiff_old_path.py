"""The launch differential's old path compares what a hook decided, not how fast the machine ran it (C9).

launchdiff._main runs each hook of an event as its own process. A hook that answers after its registered
timeout only because the machine is loaded must be compared by its answer, not recorded as 'timeout'
(which the launcher, on its own clock, did not meet); a hook that never answers still ends as 'timeout'.
"""
from __future__ import annotations

import io
import json
import sys

from tests.replay import launchdiff


def _old_path(monkeypatch, hooks: list) -> list:
    spec = {"hooks": hooks, "payload": "{}", "env": {"PATH": "/usr/bin:/bin"}, "cwd": "/"}
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(spec)))
    monkeypatch.setattr(sys, "stdout", out)
    assert launchdiff._main() == 0
    return json.loads(out.getvalue())


def test_a_hook_slower_than_its_timeout_is_compared_by_its_answer(monkeypatch):
    rec, = _old_path(monkeypatch, [{"hook": "hooks/slow.py", "timeout": 1,
                                    "command": "sleep 1.5; echo decided; exit 2"}])
    assert (rec["rc"], rec["stdout"], rec["timeout"]) == (2, "decided\n", 1)


def test_a_hook_that_never_answers_still_ends_as_timeout(monkeypatch):
    monkeypatch.setattr(launchdiff, "OLD_PATH_SLACK", 1)
    rec, = _old_path(monkeypatch, [{"hook": "hooks/hung.py", "timeout": 1, "command": "sleep 5"}])
    assert (rec["rc"], rec["stderr"]) == ("timeout", "timeout")
