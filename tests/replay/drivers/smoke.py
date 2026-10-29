"""Smoke driver: proves the core end to end on any harness tree.

One session: SessionStart, one plain prompt, a few ordinary main-agent tool
calls (one of which fails, to show a failing call is an error tool_result and
the replay goes on), one foreground dispatch of a subagent with a trivial
read-only task, and a Stop. It runs no command text, so it needs no cmdtext.
"""
from __future__ import annotations

PIPELINE = "smoke"

TASK = (
    "Problem: a reader needs to know what the add function of the toy package returns.\n"
    "Acceptance criteria: the answer names the value add returns for two numbers.\n"
    "Constraints: look only at the toy package.\n"
    "DO NOT: modify, create or delete any file; DO NOT run tests, builds or version-control commands."
)


def _explore(sub):
    project = sub.rp.layout.project
    sub.read(f"{project}/toy/__init__.py", label="sub Read")
    sub.tool("Grep", {"pattern": "return", "path": f"{project}/toy", "output_mode": "files_with_matches"},
             label="sub Grep")


def run(rp):
    project = rp.layout.project
    s = rp.session()
    s.prompt("What does the add function in the toy package return? Look, then run the tests.", label="prompt")
    s.read(f"{project}/toy/__init__.py", label="main Read")
    s.tool("Glob", {"pattern": "**/*.py", "path": project}, label="main Glob")
    s.tool("Grep", {"pattern": "def add", "path": project, "output_mode": "files_with_matches"}, label="main Grep")
    s.bash("git status --short", "Show working tree status", label="main Bash git-status")
    s.bash("python3 -m pytest -q -p no:cacheprovider", "Run the toy tests", label="main Bash pytest")
    s.bash("test -f CHANGELOG.md", "Check for a changelog", label="main Bash failing")
    s.edit(f"{project}/README.md", "# toy\n", "# toy\n\nA toy package: add and sub.\n", label="main Edit")
    s.todo([{"content": "Answer the question", "status": "in_progress", "activeForm": "Answering the question"}],
           label="main TodoWrite")
    s.dispatch("Explore", TASK, description="Describe toy.add", body=_explore,
               result="add(a, b) returns a + b.", label="main Agent(Explore)")
    s.stop("add(a, b) returns a + b, and the toy tests pass.", label="Stop")
