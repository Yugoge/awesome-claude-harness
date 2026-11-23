#!/usr/bin/env python3
"""A3.a (hooks/subagentstop-artifact-contract-enforce.py, _file_lists_errors) on the shapes of the stops it blocked
in live use: a dev dispatched to repair an older cycle's bookkeeping file (its qa-report, its spec, its context under
docs/dev/) edits that file, lists it, and was told "declared but not written by this dev" until it dropped the file
from its lists; naming it in Bash, the hint of another block, did not help, so the same agent was blocked again.

The written side of the comparison dropped the bookkeeping trees (command_span.EXCLUDED_TREES) while the declared
side kept them, so such a path could never count as written. Now a declared path is judged against everything the
dev wrote or named; only the "written but not declared" side leaves those trees out (nothing in them lands)."""
from __future__ import annotations

from test_g2_file_lists import Cycle, _blocked, _clean, base  # noqa: E402  (hooks/tests on sys.path)

OLD = "docs/dev/qa-report-20260101-000000.json"


def _repair(c: Cycle, rel: str = OLD):
    """An older cycle's bookkeeping file the dispatch asks this dev to correct, and the dev's Edit of it."""
    base._write(c.project / rel, {"qa": {"status": "pass"}})
    edit = ("Edit", {"file_path": c.path(rel), "old_string": "pass", "new_string": "warning"}, True)
    base._write(c.project / rel, {"qa": {"status": "warning"}})
    return [edit]


def test_an_older_cycles_bookkeeping_file_the_dev_edited_counts_as_written(tmp_path):
    c = Cycle(tmp_path)
    d = c.dispatch("session-old", "agent-repairdev", _repair(c))
    _clean(c.stop(d, [OLD], []))


def test_the_repeat_after_naming_it_in_bash_does_not_happen(tmp_path):
    """The recorded repeat: the agent's second stop, after `ls -l <path>`, with the same lists."""
    c = Cycle(tmp_path)
    calls = _repair(c) + [("Bash", {"command": f"ls -l {OLD}", "description": "name it"}, True)]
    d = c.dispatch("session-old", "agent-repairdev2", calls)
    _clean(c.stop(d, [OLD], []))


def test_a_bookkeeping_file_the_dev_never_touched_is_still_caught(tmp_path):
    c = Cycle(tmp_path)
    base._write(c.project / "docs/dev/spec-20260101-000000.md", "# spec\n")
    d = c.dispatch("session-old", "agent-claimdev", _repair(c))
    claimed = "docs/dev/spec-20260101-000000.md"
    _blocked(c.stop(d, [OLD, claimed], []), d["report"], claimed, "(none)",
             f"files_modified: {OLD}; files_created: []")


def test_a_bookkeeping_file_written_and_not_listed_needs_no_declaration(tmp_path):
    c = Cycle(tmp_path)
    d = c.dispatch("session-old", "agent-quietdev", _repair(c))
    _clean(c.stop(d, [], []))
