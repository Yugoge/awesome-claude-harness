"""A shell write into the caller's own scratch through a variable set to a literal in the same command.

hooks/pretool-tool-policy.py reads a Bash command's write targets statically. A target that expands a
variable assigned a literal path earlier in the same command, in a statement that surely runs, is
judged by that path, so a write into the caller's own scratch through ``S=<own>; ... $S/x`` is
allowed like the same write with the path written out. A variable the scan cannot resolve stays
refused, and the refusal names the caller's own scratch directory as a literal path to use.
"""
from __future__ import annotations

import pytest

from test_tool_policy_own_scratch import NAMED, PROJECTS, SID, run, session_root

QA = ("a0123456789abcdef", "qa")


def own_dirs(tmp_path, project):
    return [str(session_root(tmp_path) / SID / "qa" / QA[0]), f"{project}/.claude/scratch/{SID}/qa/{QA[0]}"]


def recorded(own, repo):
    """The shape of the recorded call (2026-11-21), neutral names: S is the caller's own scratch."""
    return (f"S={own}; R={repo}; mkdir -p $S/export && git -C $R archive 46693e7ea | tar -x -C $S/export && "
            "for r in AAA/monitor/run_one BBB/monitor/run_two; do mkdir -p $S/export/data/$(dirname $r) && "
            "cp -a $R/data/$r $S/export/data/$r; done ")


@pytest.mark.parametrize("project", PROJECTS)
def test_the_recorded_call_into_own_scratch_through_a_variable_is_allowed(tmp_path, project):
    for own in own_dirs(tmp_path, project):
        proc = run(tmp_path, project, "Bash", {"command": recorded(own, project)}, QA)
        assert proc.returncode == 0, (own, proc.stderr)


@pytest.mark.parametrize("command", ["S={own}; echo x > $S/a.txt", "S={own}; cp a.txt \"$S/b/a.txt\"",
                                     "S={own} && mkdir -p ${{S}}/d && echo x > ${{S}}/d/f"])
def test_a_variable_set_to_the_own_path_is_judged_by_that_path(tmp_path, command):
    project = PROJECTS[0]
    own = own_dirs(tmp_path, project)[0]
    proc = run(tmp_path, project, "Bash", {"command": command.format(own=own)}, QA)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("command", ["S={own}; S=/etc/x; echo x > $S/a.txt",
                                     "S={other}; echo x > $S/a.txt",
                                     "S=/var/tmp/x; for r in a b; do cp f $S/$r; done"])
def test_a_variable_set_to_a_path_not_own_is_refused_as_that_path(tmp_path, command):
    project = PROJECTS[0]
    own = own_dirs(tmp_path, project)[0]
    other = str(session_root(tmp_path) / SID / "qa" / "a9999999999999999")
    proc = run(tmp_path, project, "Bash", {"command": command.format(own=own, other=other)}, QA)
    assert proc.returncode == 2, proc.stderr


@pytest.mark.parametrize("command", ["S=$(mktemp -d /var/tmp/x-XXXXXX); echo x > $S/a.txt",
                                     "echo x > $UNSET_ELSEWHERE/a.txt",
                                     "if true; then S={own}; fi; echo x > $S/a.txt"])
def test_an_unresolvable_variable_is_refused_naming_the_own_directory(tmp_path, command):
    project = PROJECTS[0]
    own = own_dirs(tmp_path, project)[0]
    proc = run(tmp_path, project, "Bash", {"command": command.format(own=own)}, QA)
    assert proc.returncode == 2, proc.stderr
    found = NAMED.search(proc.stderr)
    assert found and found.group(1) == own, proc.stderr
