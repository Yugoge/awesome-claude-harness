"""A refusal of hooks/pretool-tool-policy.py names a means the caller's next call may take literally.

Two refusals that named none: the watcher tool (Monitor), which no role's list holds, refused with no
other way to wait; and a qa write outside system temp and scratch (a memory-backed path) refused with
no directory the agent may use. The first now names the wait the CLI's own sleep guard suggests, as a
Bash call; the second names the caller's own scratch directory as a literal path. Each named means is
then put to the same gate for the same caller and passes.
"""
from __future__ import annotations

import json
import re

import pytest

from test_tool_policy_own_scratch import NAMED, PROJECTS, run, writes

LOOP = re.compile(r"Bash call \(timeout up to (\d+) ms\): (until <check>; do sleep \d+; done);")
ROLES = ("dev", "qa", "ba", "user", "changelog-analyst")


@pytest.mark.parametrize("role", ROLES)
def test_a_refused_monitor_names_a_wait_the_same_role_may_run(tmp_path, role):
    caller, project = ("a" + role.replace("-", "").ljust(15, "0")[:15], role), PROJECTS[0]
    refused = run(tmp_path, project, "Monitor", {"command": "until [ -s out.txt ]; do sleep 2; done",
                                                  "description": "wait", "timeout_ms": 600000}, caller)
    assert refused.returncode == 2 and "tool Monitor not in allowed_tools" in refused.stderr, refused.stderr
    found = LOOP.search(refused.stderr)
    assert found and "run_in_background: true" in refused.stderr, refused.stderr
    loop = found.group(2).replace("<check>", f"[ -s {project}/out.txt ]")
    for tool_input in ({"command": loop, "timeout": int(found.group(1))},
                       {"command": "python3 -m pytest -q", "run_in_background": True}):
        proc = run(tmp_path, project, "Bash", tool_input, caller)
        assert proc.returncode == 0, (tool_input, proc.stderr)


@pytest.mark.parametrize("project", PROJECTS)
@pytest.mark.parametrize("target", ["/dev/shm/r07-backup.json", "/srv/r07-backup.json"])
def test_a_refused_qa_write_outside_temp_names_its_own_directory(tmp_path, project, target):
    caller = ("aqa000000000000a", "qa")
    for tool, tool_input in [("Write", {"file_path": target, "content": "x"}),
                             ("Bash", {"command": f"cd {project}; cp -n docs/r.json {target} 2>/dev/null"})]:
        refused = run(tmp_path, project, tool, tool_input, caller)
        assert refused.returncode == 2 and "not in allowed_write_path_prefixes" in refused.stderr, refused.stderr
        found = NAMED.search(refused.stderr)
        assert found, refused.stderr
        own = found.group(1)
        assert own.startswith(f"{project}/.claude/scratch/") and caller[0] in own, own
        for next_tool, next_input in writes(own):
            proc = run(tmp_path, project, next_tool, next_input, caller)
            assert proc.returncode == 0, (next_tool, json.dumps(next_input), proc.stderr)
