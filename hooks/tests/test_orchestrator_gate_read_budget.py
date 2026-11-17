"""OB-L01: the orchestrator gate's budget for read-only and retrieval tools.

hooks/pretool-orchestrator-gate.py allowed the main agent one call per non-whitelisted tool name per
turn, and read-only and retrieval tools were not whitelisted: a turn's second WebSearch, WebFetch,
Context7 lookup, LSP query, BashOutput/TaskOutput read or MCP resource read was refused, while
CLAUDE.md's Working Practice asks for Context7 docs and allows 1-3 WebSearch queries directly.

Now the built-in read-only tools (LSP, TaskOutput, BashOutput, ReadMcpResourceTool,
ListMcpResourcesTool) pass uncounted, and the retrieval tools (WebSearch, WebFetch and the Context7
tools, each listed by exact name) get 3 calls per tool name per turn. An Agent dispatch does not
refill that budget, not even inside the open /dev-overnight window: the calls of one message pass
PreToolUse together. Every other non-whitelisted tool keeps its one call per turn, and an MCP tool is
never let through by a name pattern.

Each case runs the gate (and, for the registered pipeline, hooks/pretool-launch.py) as a subprocess
with the PreToolUse payload the CLI sends; HOME, state dir, project and TMPDIR live in tmp_path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "hooks" / "pretool-orchestrator-gate.py"
LAUNCH = ROOT / "hooks" / "pretool-launch.py"
REFUSED = "used consecutively beyond limit"

INPUTS = {
    "WebSearch": {"query": "python asyncio wait_for cancel"},
    "WebFetch": {"url": "https://example.com/doc", "prompt": "summarize"},
    "mcp__context7__resolve-library-id": {"libraryName": "pydantic"},
    "mcp__context7__get-library-docs": {"context7CompatibleLibraryID": "/pydantic/pydantic"},
    "LSP": {"operation": "goToDefinition", "filePath": "/x.py", "line": 1, "character": 1},
    "BashOutput": {"bash_id": "b1"},
    "TaskOutput": {"task_id": "t1"},
    "ReadMcpResourceTool": {"server": "docs", "uri": "docs://a"},
    "ListMcpResourcesTool": {},
}


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


class Session:
    def __init__(self, tmp_path: Path, first_prompt: str = "look this up"):
        self.tmp, self.sid = tmp_path, str(uuid.uuid4())
        self.home = tmp_path / "home"
        self.project = tmp_path / "project"
        self.state = tmp_path / "state"
        for d in (self.project / ".claude", self.state, tmp_path / "tmp"):
            d.mkdir(parents=True, exist_ok=True)
        tdir = self.home / ".claude" / "projects" / "-project"
        tdir.mkdir(parents=True)
        self.transcript = tdir / f"{self.sid}.jsonl"
        self.transcript.write_text("")
        with self.transcript.open("a") as handle:
            handle.write(json.dumps({"type": "user", "message": {"role": "user", "content": first_prompt}}) + "\n")

    def overnight(self) -> None:
        (self.project / ".claude" / f"overnight-state-{self.sid}.json").write_text(json.dumps({
            "session_id": self.sid, "start_time": _iso(timedelta(hours=-1)), "end_time": _iso(timedelta(hours=1)),
            "current_phase": "exploring"}))

    def run(self, tool: str, tool_input: dict | None = None, hook: Path = GATE) -> subprocess.CompletedProcess:
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
               "CLAUDE_HOME": str(ROOT), "CLAUDE_STATE_DIR": str(self.state), "TMPDIR": str(self.tmp / "tmp"),
               "CLAUDE_PROJECT_DIR": str(self.project), "GIT_CEILING_DIRECTORIES": str(self.tmp),
               "PYTHONDONTWRITEBYTECODE": "1"}
        body = {"session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(self.project),
                "hook_event_name": "PreToolUse", "permission_mode": "default", "tool_name": tool,
                "tool_input": INPUTS.get(tool, {}) if tool_input is None else tool_input}
        return subprocess.run([sys.executable, str(hook)], input=json.dumps(body), capture_output=True,
                              text=True, env=env, cwd=self.project, timeout=120)

    def allowed(self, tool: str, tool_input: dict | None = None, hook: Path = GATE) -> bool:
        p = self.run(tool, tool_input, hook)
        assert p.returncode in (0, 2), (p.returncode, p.stdout, p.stderr)
        if p.returncode == 2:
            assert REFUSED in p.stderr, p.stderr
        return p.returncode == 0

    def dispatch(self) -> None:
        p = self.run("Agent", {"subagent_type": "general-purpose", "prompt": "x", "run_in_background": False})
        assert p.returncode == 0, p.stderr


@pytest.mark.parametrize("tool", ["WebSearch", "WebFetch"])
def test_second_and_third_web_retrieval_in_a_turn_pass(tmp_path, tool):
    s = Session(tmp_path)
    assert [s.allowed(tool) for _ in range(3)] == [True, True, True]


@pytest.mark.parametrize("tool", ["mcp__context7__resolve-library-id", "mcp__context7__get-library-docs"])
def test_second_context7_lookup_passes(tmp_path, tool):
    s = Session(tmp_path)
    assert s.allowed(tool) and s.allowed(tool)


@pytest.mark.parametrize("tool", ["LSP", "BashOutput", "TaskOutput", "ReadMcpResourceTool", "ListMcpResourcesTool"])
def test_read_only_builtins_pass_uncounted(tmp_path, tool):
    s = Session(tmp_path)
    assert all(s.allowed(tool) for _ in range(6))
    assert not (s.state / f"claude-tool-streak-{s.sid}.json").exists(), "a read-only tool writes no count"


def test_fourth_websearch_refused_even_after_a_dispatch(tmp_path):
    s = Session(tmp_path)
    assert s.allowed("WebSearch") and s.allowed("WebSearch")
    s.dispatch()
    assert s.allowed("WebSearch")
    p = s.run("WebSearch")
    assert p.returncode == 2 and "WebSearch used consecutively beyond limit (4/3)" in p.stderr, p.stderr
    assert "retrieval tool" in p.stderr


def test_overnight_dispatch_keeps_the_retrieval_count(tmp_path):
    s = Session(tmp_path, "/dev-overnight 1h harden the toy package")
    s.overnight()
    for _ in range(3):
        assert s.allowed("WebFetch")
    assert s.allowed("Edit", {"file_path": str(s.project / "a.md"), "old_string": "a", "new_string": "b"})
    s.dispatch()
    assert not s.allowed("WebFetch"), "the overnight dispatch does not refill the retrieval budget"
    assert s.allowed("Edit", {"file_path": str(s.project / "a.md"), "old_string": "a", "new_string": "b"}), \
        "the overnight dispatch still resets the once-per-turn tools"


def test_second_edit_still_refused(tmp_path):
    s = Session(tmp_path)
    edit = {"file_path": str(s.project / "a.md"), "old_string": "a", "new_string": "b"}
    assert s.allowed("Edit", edit)
    p = s.run("Edit", edit)
    assert p.returncode == 2 and "Edit used consecutively beyond limit (2/1)" in p.stderr, p.stderr
    assert "retrieval tool" not in p.stderr


def test_second_github_create_pull_request_still_refused(tmp_path):
    s = Session(tmp_path)
    pr = {"owner": "o", "repo": "r", "title": "t", "head": "h", "base": "main"}
    assert s.allowed("mcp__github__create_pull_request", pr)
    assert not s.allowed("mcp__github__create_pull_request", pr)


@pytest.mark.parametrize("tool", ["mcp__thirdparty__get_records", "mcp__thirdparty__search_and_delete",
                                  "mcp__context7__get_records", "mcp__notcontext7__resolve-library-id"])
def test_unlisted_mcp_tool_named_like_a_reader_keeps_one_call(tmp_path, tool):
    s = Session(tmp_path)
    assert s.allowed(tool)
    assert not s.allowed(tool), "an MCP tool passes only by its exact listed name"


def test_registered_pipeline(tmp_path):
    """Through hooks/pretool-launch.py, the PreToolUse hook settings.json registers for every tool."""
    s = Session(tmp_path)
    assert [s.allowed("WebSearch", hook=LAUNCH) for _ in range(4)] == [True, True, True, False]
    assert s.allowed("LSP", hook=LAUNCH) and s.allowed("LSP", hook=LAUNCH)
    assert s.allowed("mcp__thirdparty__get_records", hook=LAUNCH)
    assert not s.allowed("mcp__thirdparty__get_records", hook=LAUNCH)
