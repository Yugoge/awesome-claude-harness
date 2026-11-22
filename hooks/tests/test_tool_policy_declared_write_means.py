"""A write refused because another dispatch declares the path names the means that works (D8).

The recorded case: a /dev fan-out lane's dev, fixing one contract cell, also had to change the same cell in its
lane's ticket and context, which the lane's BA dispatch declares; tool-policy refused both edits with no way
forward, and the test that compares the ticket and context mirrors stayed failing. The files are the BA's
product, so the rule stands; the refusal names who owns the path and how the change reaches it: the dev names
it in its report, and the orchestrator re-dispatches the owning role for that task, whose write of it passes.
The main agent is told to make that re-dispatch itself.
"""
from __future__ import annotations

import re

import pytest

from test_tool_policy_derived_permission import PROJECT, Session, _block, _denial, _obligation

LANE_TASK = "20261028-101010-r00"
TICKET = f"docs/dev/ticket-{LANE_TASK}.md"
CONTEXT = f"docs/dev/context-{LANE_TASK}.json"
MEANS = re.compile(r"^tool-policy\.v1 means: (\S+) owns (\S+); .*re-dispatch(?:es)? \1 for task (\S+) "
                   r"\(same subagent_type, task_id, lane and obligation template\)", re.M)


def _edit(path: str) -> dict:
    return {"file_path": str(PROJECT / path), "old_string": '"f"', "new_string": '"u"'}


def _lane(tmp_path) -> Session:
    s = Session(tmp_path / "projects")
    s.command("dev")
    s.ba = s.dispatch("You are the BA subagent.\n" + _block(_obligation("ba", "fanout-lane", TICKET, CONTEXT,
                                                                         task=LANE_TASK)), "ba")
    s.dev = s.dispatch("You are the dev subagent.\n" + _block(_obligation(
        "dev", "fanout-lane", f"docs/dev/dev-report-{LANE_TASK}.json", task=LANE_TASK)), "dev")
    return s


@pytest.mark.parametrize("path", [TICKET, CONTEXT])
@pytest.mark.parametrize("caller", ["dev", "main"])
def test_the_refusal_names_the_owner_and_the_redispatch_that_passes(tmp_path, path, caller):
    s = _lane(tmp_path)
    refused = s.run(tmp_path, "Edit", _edit(path), (s.dev, "dev") if caller == "dev" else None)
    assert _denial(refused)["deny_reason"].endswith("only ba writes this artifact (D8)"), refused.stderr
    found = MEANS.search(refused.stderr)
    assert found, refused.stderr
    role, owned, task = found.groups()
    assert (role, owned, task) == ("ba", str(PROJECT / path), LANE_TASK), refused.stderr
    if caller == "dev":
        assert "in your report" in refused.stderr, refused.stderr
    # The means, taken as named: the orchestrator re-dispatches that role for that task with the change named.
    again = s.dispatch(f"You are the BA subagent. Change requested by the dev lane: {path}.\n"
                       + _block(_obligation(role, "fanout-lane", TICKET, CONTEXT, task=task)), role)
    passed = s.run(tmp_path, "Edit", _edit(path), (again, role))
    assert passed.returncode == 0, passed.stderr
