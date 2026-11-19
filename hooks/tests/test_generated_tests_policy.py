#!/usr/bin/env python3
"""Generated tests against docs/reference/generated-tests-policy.md: git ignores
tests/generated/ (outside the pinned directories) and the tree stays out of
version control, so a generated test is no deliverable.

agents/dev.md's "Generated tests" rule says which report list a generated test
goes in; the two checks that read the lists must let a dev that follows it
through: its own stop (hooks/subagentstop-artifact-contract-enforce.py, A3.a
file_lists_differ) and the QA dispatch that names its report
(hooks/pretool-gitignore-preflight.py). What each check exists to stop is still
stopped: a git-ignored real deliverable refuses the QA dispatch, and a declared
file the dev did not write is a stop finding.

The project is a throwaway git repository whose .gitignore carries the entry a
project gets (`/tests/generated/`); transcripts are synthetic (test_g2_file_lists).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import pytest

import test_artifact_contract_enforce as base  # noqa: E402  (hooks/tests on sys.path)
import test_g2_file_lists as g2  # noqa: E402

PREFLIGHT = base.REPO_ROOT / "hooks" / "pretool-gitignore-preflight.py"
GENERATED = [f"tests/generated/{g2.TASK}/test_AC{n:02d}_{uid}.py"
             for n, uid in ((1, "0a1b2c3d4e5f6a7b"), (2, "1b2c3d4e5f6a7b8c"), (3, "2c3d4e5f6a7b8c9d"))]
SKELETON = 'AC_UID = "0a1b2c3d4e5f6a7b"\n\n\ndef test_ac():\n    assert True\n'
# The dev's one interpreter call over the manifest: it names no test file.
LOOP = ("python3 -c \"import json; m = json.load(open('tests/generated/%s/manifest.json')); "
        "[open(e['file'], 'w').write(e['skeleton']) for e in m['active_tests']]\"" % g2.TASK)


def dev_md_lists() -> list:
    """The report lists agents/dev.md's Generated tests rule puts a written skeleton in."""
    text = g2.DEV_MD.read_text(encoding="utf-8")
    rule = text.split("**Generated tests**", 1)[1].split("\n\n", 1)[0]
    return re.findall(r"goes in `dev\.(files_created|files_modified)`", rule)


def cycle(tmp_path, ignore=("/tests/generated/",)) -> g2.Cycle:
    c = g2.Cycle(tmp_path)
    base._write(c.project / ".gitignore", "".join(f"{p}\n" for p in ignore))
    g2._git(c.project, "add", ".gitignore")
    g2._git(c.project, "commit", "-q", "-m", "ignore")
    return c


def dev_calls(c: g2.Cycle, by: str) -> list:
    """A dev of a cycle the test-writer ran: Reads its sentinel and the manifest, Writes
    src/new.py, then writes each generated test from its skeleton, with one Bash call over
    the manifest (`bash`) or one Write per test (`write`). The driver puts the files on disk."""
    sentinel = c.project / ".claude" / "dev-registry" / f"dev-{g2.TASK}" / "dev.json"
    base._write(sentinel, {"agent_type": "dev"})
    manifest = c.project / "tests" / "generated" / g2.TASK / "manifest.json"
    base._write(manifest, {"task_id": g2.TASK, "active_tests": [{"file": f, "skeleton": SKELETON} for f in GENERATED]})
    base._write(c.project / "src" / "new.py", "def new():\n    return 1\n")
    for rel in GENERATED:
        base._write(c.project / rel, SKELETON)
    calls = [("Read", {"file_path": str(sentinel)}, True), ("Read", {"file_path": str(manifest)}, True),
             ("Write", {"file_path": c.path("src/new.py"), "content": "def new():\n    return 1\n"}, True)]
    if by == "bash":
        return calls + [("Bash", {"command": LOOP, "description": "Write the generated tests"}, True)]
    return calls + [("Write", {"file_path": c.path(rel), "content": SKELETON}, True) for rel in GENERATED]


def qa_dispatch(c: g2.Cycle, report: str) -> subprocess.CompletedProcess:
    """The main agent's QA dispatch naming the dev report, through the gitignore rule."""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(c.project), HOME=str(c.home),
               CLAUDE_CONFIG_DIR=str(c.home / ".claude"))
    env.pop("CLAUDE_HOME", None)
    prompt = f"Dev report file: {report}\nVerify every acceptance criterion and write your QA report.\n"
    payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "qa", "description": "QA", "prompt": prompt}}
    return subprocess.run([sys.executable, str(PREFLIGHT)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, cwd=str(c.project), timeout=60)


@pytest.mark.parametrize("by", ["bash", "write"])
def test_dev_following_dev_md_passes_its_stop_and_its_qa_dispatch(tmp_path, by):
    """A dev that lists the generated tests where agents/dev.md says: its stop has no
    file_lists_differ and the QA dispatch naming its report is not refused. Before the
    rule followed the policy it put them in dev.files_created: the Bash-written tests
    were `declared but not written by this dev`, the Written ones refused QA."""
    c = cycle(tmp_path)
    d = c.dispatch(f"session-{by}", f"agent-{by}", dev_calls(c, by))
    lists = {"files_modified": [], "files_created": ["src/new.py"]}
    for key in dev_md_lists():
        lists[key] += GENERATED
    g2._clean(c.stop(d, lists["files_modified"], lists["files_created"]))
    qa = qa_dispatch(c, d["report"])
    assert qa.returncode == 0 and "BLOCKED" not in qa.stderr, qa.stderr


def test_listed_generated_tests_are_dropped_not_named(tmp_path):
    """A report that still lists Bash-written generated tests gets the stop finding with lists
    without them, and no advice to name them and keep them listed (the QA dispatch would refuse
    them): git ignores them, nothing lands them."""
    c = cycle(tmp_path)
    d = c.dispatch("session-listed", "agent-listed", dev_calls(c, "bash"))
    lines = g2._blocked(c.stop(d, [], ["src/new.py"] + GENERATED), d["report"], ", ".join(GENERATED), "(none)",
                        "files_modified: []; files_created: src/new.py")
    assert "fix" not in lines, lines


def test_ignored_real_deliverable_still_refuses_qa_dispatch(tmp_path):
    """Guard: a deliverable the dev wrote under a path the project ignores (a build output)
    still refuses the QA dispatch naming the report."""
    c = cycle(tmp_path, ignore=("/tests/generated/", "/build/"))
    calls = dev_calls(c, "bash")
    base._write(c.project / "build" / "app.js", "module.exports = 1;\n")
    calls.append(("Write", {"file_path": c.path("build/app.js"), "content": "module.exports = 1;\n"}, True))
    d = c.dispatch("session-build", "agent-build", calls)
    g2._clean(c.stop(d, [], ["build/app.js", "src/new.py"]))
    qa = qa_dispatch(c, d["report"])
    assert qa.returncode == 2, qa.stderr
    assert qa.stderr.splitlines()[0] == "BLOCKED: gitignored deliverables detected: build/app.js", qa.stderr


def test_declared_unwritten_non_generated_file_still_gets_stop_finding(tmp_path):
    """Guard: a declared file the dev did not write and that is not a generated test is a stop
    finding: one another session changed (named-and-kept advice stays, git has a change for it)
    and one nobody changed."""
    c = cycle(tmp_path)
    calls = dev_calls(c, "bash")
    base._write(c.project / "src" / "app.py", "x = 2\n")  # another session's change
    d = c.dispatch("session-peer", "agent-peer", calls)
    lines = g2._blocked(c.stop(d, ["src/app.py"], ["src/new.py"]), d["report"], "src/app.py", "(none)",
                        "files_modified: []; files_created: src/new.py")
    assert lines.get("fix") == "name it and keep it listed", lines
    d = c.dispatch("session-still", "agent-still", calls)
    g2._blocked(c.stop(d, ["gen.py"], ["src/new.py"]), d["report"], "gen.py", "(none)",
                "files_modified: []; files_created: src/new.py")
