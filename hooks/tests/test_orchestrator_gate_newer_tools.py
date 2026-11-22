"""T4: Monitor, TaskStop, ListAgents and PushNotification for the main agent (report section 6).

hooks/pretool-orchestrator-gate.py allowed each of these once per turn, as any tool outside its
whitelist. Now:

- TaskStop, ListAgents and PushNotification are always allowed (no count of their own, Bash's
  count untouched). TaskCreate, TaskUpdate, TaskList and TaskGet stay once per turn.
- Monitor is whitelisted but runs an arbitrary shell command, so each call counts against the Bash
  cap of 5 in Bash's own counter: Bash and Monitor calls add up, the 6th of either is refused, and an
  Agent dispatch or the next prompt resets the count for both.
- Monitor is refused on a CLI below 2.1.314, where the CLI did not run Bash-matcher hooks on
  Monitor's command. The version is the one on the latest transcript record that carries one (the
  payload has none; CLAUDE_CODE_VERSION in a hook's environment is inherited and was measured stale).
  No readable version: refused (fail closed). /do does not lift the refusal; an /allow grant naming
  Monitor passes one call.
- hooks/pretool-block-background-tasks.py's no-background rule does not cover Monitor (a watcher).
- The CLI delivers a Monitor command to Bash-matcher hooks registered in settings.json as a Bash
  call (measured on 2.1.325); pretool-bash-safety.sh is one, and stays registered that way.

The Bash probe here is a command lib/bash_read_only does not prove read-only (python3 runs code): a
proven read-only command passes uncounted (OB-L03) and would never reach the shared cap. CLAUDE.md's
"Always allowed" line also names the gate's READ_ONLY_ALLOWED tools after "and the read-only" (OB-L01).

Each hook runs as a subprocess with a PreToolUse payload as the CLI sends it, its state dir, HOME,
project and TMPDIR inside the test's tmp_path.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "hooks" / "pretool-orchestrator-gate.py"
BACKGROUND = ROOT / "hooks" / "pretool-block-background-tasks.py"
CAPPED = "used consecutively beyond limit"
VERSION_REFUSED = "Monitor needs Claude Code 2.1.314 or later"


class Session:
    def __init__(self, tmp_path: Path, version: str | None = "2.1.325"):
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
        self.typed("watch the CI run", version)

    def typed(self, text: str, version: str | None) -> None:
        record = {"type": "user", "message": {"role": "user", "content": text}, "sessionId": self.sid}
        if version is not None:
            record["version"] = version
        with self.transcript.open("a") as handle:
            handle.write(json.dumps({"type": "queue-operation", "operation": "enqueue"}) + "\n")
            handle.write(json.dumps(record) + "\n")

    def env(self) -> dict:
        return {"PATH": os.environ["PATH"], "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
                "CLAUDE_STATE_DIR": str(self.state), "TMPDIR": str(self.tmp / "tmp"),
                "CLAUDE_PROJECT_DIR": str(self.project), "GIT_CEILING_DIRECTORIES": str(self.tmp),
                "PYTHONDONTWRITEBYTECODE": "1",
                # inherited from the launcher, and stale: the gate must not believe it
                "CLAUDE_CODE_VERSION": "2.1.999"}

    def run(self, hook: Path, tool: str, tool_input: dict | None = None,
            transcript: str | None = None) -> subprocess.CompletedProcess:
        body = {"session_id": self.sid, "transcript_path": str(self.transcript) if transcript is None else transcript,
                "cwd": str(self.project), "hook_event_name": "PreToolUse", "permission_mode": "default",
                "tool_name": tool, "tool_input": tool_input or {}, "tool_use_id": f"toolu_{uuid.uuid4().hex[:20]}"}
        return subprocess.run([sys.executable, str(hook)], input=json.dumps(body), capture_output=True,
                              text=True, env=self.env(), cwd=self.project, timeout=60)

    def gate(self, tool: str, tool_input: dict | None = None, **kw) -> subprocess.CompletedProcess:
        return self.run(GATE, tool, tool_input, **kw)

    def bash(self) -> subprocess.CompletedProcess:
        return self.gate("Bash", {"command": "python3 x.py", "description": "probe"})

    def monitor(self, **kw) -> subprocess.CompletedProcess:
        return self.gate("Monitor", {"description": "CI run", "timeout_ms": 300000,
                                     "command": "gh run watch 1 --exit-status"}, **kw)

    def dispatch(self) -> None:
        p = self.gate("Agent", {"subagent_type": "general-purpose", "prompt": "x", "run_in_background": False})
        assert p.returncode == 0, p.stderr

    def do_consent(self) -> None:
        (self.state / f"claude-orchestrator-consent-{self.sid}.flag").write_text("true")

    def allow(self, tool: str) -> None:
        grants = self.state / "claude-grants"
        grants.mkdir(parents=True, exist_ok=True)
        now = time.time()
        (grants / f"{self.sid}.json").write_text(json.dumps({
            "task_id": self.sid, "session_id": self.sid, "allowed_operations": [{"op": tool}],
            "created_at": now, "expires_at": now + 300}))

    def streak_file(self) -> Path:
        return self.state / f"claude-tool-streak-{self.sid}.json"

    def streak(self) -> dict:
        return json.loads(self.streak_file().read_text())


def _verdict(p: subprocess.CompletedProcess, refusal: str = CAPPED) -> bool:
    assert p.returncode in (0, 2), (p.returncode, p.stderr)
    if p.returncode == 2:
        assert refusal in p.stderr, p.stderr
    return p.returncode == 0


@pytest.fixture
def session(tmp_path):
    return Session(tmp_path)


# --- TaskStop, ListAgents, PushNotification: always allowed --------------------------------------

@pytest.mark.parametrize("tool, tool_input", [
    ("TaskStop", {"task_id": "bmepjcmo8"}),
    ("ListAgents", {}),
    ("PushNotification", {"message": "overnight run finished", "status": "proactive"}),
])
def test_always_allowed_newer_tools_pass_every_call_and_leave_bash_count(session, tool, tool_input):
    for _ in range(3):
        assert session.bash().returncode == 0
    before = session.streak()
    for n in range(4):
        p = session.gate(tool, tool_input)
        assert p.returncode == 0, f"{tool} call {n + 1} in one turn: {p.stderr}"
    assert session.streak() == before, f"{tool} must neither count itself nor touch Bash's count"


@pytest.mark.parametrize("tool, tool_input", [
    ("TaskCreate", {"subject": "a", "description": "b"}),
    ("TaskUpdate", {"taskId": "1", "status": "in_progress"}),
    ("TaskList", {}),
    ("TaskGet", {"taskId": "1"}),
])
def test_task_list_tools_stay_once_per_turn(session, tool, tool_input):
    assert _verdict(session.gate(tool, tool_input))
    assert not _verdict(session.gate(tool, tool_input)), f"a second {tool} in one turn"


# --- Monitor: the Bash cap, in Bash's counter ----------------------------------------------------

def test_monitor_calls_count_against_the_bash_cap(session):
    for _ in range(5):
        assert _verdict(session.monitor())
    p = session.monitor()
    assert not _verdict(p), "the 6th Monitor call"
    assert "Monitor used consecutively beyond limit (6/5)" in p.stderr
    assert not _verdict(session.bash()), "a Bash call after five Monitor calls is the 7th of the shared count"


def test_bash_and_monitor_share_one_counter(session):
    for _ in range(3):
        assert _verdict(session.bash())
    assert _verdict(session.monitor()) and _verdict(session.monitor())
    assert session.streak()["bash_consecutive"] == {"last_tool": "Bash", "count": 5}
    p = session.bash()
    assert not _verdict(p), "the 6th of three Bash and two Monitor calls"
    assert "Bash used consecutively beyond limit (6/5)" in p.stderr
    assert session.streak()["per_tool_counts"] == {}, "Monitor has no once-per-turn count of its own"


def test_an_agent_dispatch_resets_monitor_with_bash(session):
    for _ in range(5):
        assert _verdict(session.monitor())
    assert not _verdict(session.monitor())
    session.dispatch()
    for _ in range(5):
        assert _verdict(session.monitor()), "a Monitor call after an Agent dispatch"
    assert not _verdict(session.bash())


def test_the_next_prompt_resets_monitor_with_bash(session):
    """hooks/prompt-workflow.py removes the streak file at each prompt; Monitor's count goes with it."""
    for _ in range(5):
        assert _verdict(session.bash())
    assert not _verdict(session.monitor())
    session.streak_file().unlink()
    assert _verdict(session.monitor())


def test_do_lifts_the_monitor_cap(session):
    session.do_consent()
    for _ in range(8):
        assert session.monitor().returncode == 0


# --- Monitor: refused below CLI 2.1.314, or when the version cannot be read ----------------------

@pytest.mark.parametrize("version, allowed", [
    ("2.1.313", False), ("2.1.98", False), ("1.0.128", False),
    ("2.1.314", True), ("2.1.325", True), ("2.2.0", True), ("3.0.1", True),
])
def test_monitor_needs_cli_2_1_314(tmp_path, version, allowed):
    s = Session(tmp_path, version)
    p = s.monitor()
    assert _verdict(p, VERSION_REFUSED) is allowed, (version, p.stderr)
    if not allowed:
        assert f"this session's CLI is {version}" in p.stderr
        assert not s.streak_file().exists(), "a refused Monitor call does not count"


def test_monitor_refused_when_no_record_names_the_version(tmp_path):
    """Fail closed: no version on any record (the env's CLAUDE_CODE_VERSION=2.1.999 is not believed)."""
    s = Session(tmp_path, None)
    p = s.monitor()
    assert not _verdict(p, VERSION_REFUSED) and "unknown" in p.stderr


@pytest.mark.parametrize("transcript", ["", "missing"])
def test_monitor_refused_without_a_readable_transcript(session, transcript):
    path = "" if transcript == "" else str(session.tmp / "no-such.jsonl")
    assert not _verdict(session.monitor(transcript=path), VERSION_REFUSED)


def test_the_latest_versioned_record_decides(session):
    """A session resumed by another CLI: the newest record names the CLI now writing."""
    assert _verdict(session.monitor(), VERSION_REFUSED)
    session.typed("resumed under an older CLI", "2.1.300")
    with session.transcript.open("a") as handle:  # a later record without a version does not hide it
        handle.write(json.dumps({"type": "last-prompt"}) + "\n")
    assert not _verdict(session.monitor(), VERSION_REFUSED)
    session.typed("resumed under a current CLI", "2.1.325")
    assert _verdict(session.monitor(), VERSION_REFUSED)


def test_the_version_is_found_behind_a_large_record(session):
    with session.transcript.open("a") as handle:
        handle.write(json.dumps({"type": "progress", "data": "x" * 300_000}) + "\n")
    assert _verdict(session.monitor(), VERSION_REFUSED)


def test_only_a_records_own_version_counts(tmp_path):
    """A "version" key nested in a record (a tool result's structured content) is not the CLI's."""
    s = Session(tmp_path, None)
    with s.transcript.open("a") as handle:
        handle.write(json.dumps({"type": "user", "toolUseResult": {"version": "2.1.325"}}) + "\n")
    assert not _verdict(s.monitor(), VERSION_REFUSED), "no record carries a version of its own"
    with s.transcript.open("a") as handle:
        handle.write(json.dumps({"type": "user", "toolUseResult": {"version": "1.0.0"},
                                 "version": "2.1.325"}) + "\n")
    assert _verdict(s.monitor(), VERSION_REFUSED), "the record's own version, not the nested one"


def test_a_versioned_record_cut_by_a_read_block_is_still_read(tmp_path):
    """The file is read backwards in 64 KiB blocks; a record straddling a block edge is reassembled."""
    s = Session(tmp_path, None)
    with s.transcript.open("a") as handle:
        handle.write(json.dumps({"type": "user", "pad": "x" * 70_000, "version": "2.1.325"}) + "\n")
        for _ in range(3):
            handle.write(json.dumps({"type": "progress", "data": "y" * 40_000}) + "\n")
    assert _verdict(s.monitor(), VERSION_REFUSED)


def test_do_does_not_lift_the_version_refusal(tmp_path):
    s = Session(tmp_path, "2.1.313")
    s.do_consent()
    assert not _verdict(s.monitor(), VERSION_REFUSED)


def test_the_version_check_reads_nothing_for_other_tools(tmp_path):
    s = Session(tmp_path, "2.1.313")
    assert s.bash().returncode == 0
    assert s.gate("TaskStop", {"task_id": "x"}).returncode == 0


def test_subagents_stay_exempt(tmp_path):
    s = Session(tmp_path, "2.1.313")
    body = {"session_id": s.sid, "transcript_path": str(s.transcript), "cwd": str(s.project),
            "hook_event_name": "PreToolUse", "tool_name": "Monitor", "agent_id": "a1b2c3", "agent_type": "dev",
            "tool_input": {"description": "x", "timeout_ms": 1000, "command": "true"}}
    p = subprocess.run([sys.executable, str(GATE)], input=json.dumps(body), capture_output=True, text=True,
                       env=s.env(), cwd=s.project, timeout=60)
    assert p.returncode == 0, p.stderr


# --- The no-background rule, and the Bash hooks that see Monitor's command -----------------------

def test_the_no_background_rule_does_not_cover_monitor(session):
    for tool_input in ({"description": "CI", "timeout_ms": 300000, "command": "tail -f build.log"},
                       {"description": "ws", "timeout_ms": 60000, "ws": {"url": "wss://example.invalid/feed"}}):
        p = session.run(BACKGROUND, "Monitor", tool_input)
        assert p.returncode == 0, p.stderr
    for tool in ("TaskStop", "ListAgents", "PushNotification"):
        assert session.run(BACKGROUND, tool, {}).returncode == 0


def test_bash_safety_judges_a_monitor_command_too():
    """A rule inside the matcher-less launcher sees tool_name Monitor, not Bash (measured on 2.1.325).
    pretool-bash-safety.sh is now a Bash rule of the launcher (so the owner's /allow can release its
    refusal), and the Monitor allowance relies on pretool-monitor-command.py running it on a
    Monitor's command."""
    rule = "Rule('bash-safety', 'pretool-bash-safety.sh', ('Bash',))"
    assert rule in (ROOT / "hooks" / "pretool-launch.py").read_text()
    assert rule in (ROOT / "hooks" / "pretool-monitor-command.py").read_text()


def _set_literal(node: ast.expr):
    """A set display, or frozenset() of one, as a Python set; None for anything else."""
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "frozenset" and len(node.args) == 1:
        node = node.args[0]
    return ast.literal_eval(node) if isinstance(node, ast.Set) else None


def test_the_whitelist_is_exactly_the_documented_set():
    """CLAUDE.md's Orchestrator-Only Rule names the gate's ALWAYS_ALLOWED set, then (after "and the
    read-only") its READ_ONLY_ALLOWED set (OB-L01); they move together."""
    tree = ast.parse(GATE.read_text())
    sets = {t.id: _set_literal(node.value) for node in tree.body if isinstance(node, ast.Assign)
            for t in node.targets if isinstance(t, ast.Name) and _set_literal(node.value) is not None}
    expected = {"Agent", "TodoWrite", "AskUserQuestion", "Skill", "CronCreate", "CronDelete", "CronList",
                "ScheduleWakeup", "Bash", "Read", "Glob", "Grep",
                "Monitor", "TaskStop", "ListAgents", "PushNotification"}
    read_only = {"LSP", "TaskOutput", "BashOutput", "ReadMcpResourceTool", "ListMcpResourcesTool"}
    assert sets["ALWAYS_ALLOWED"] == expected
    assert sets["READ_ONLY_ALLOWED"] == read_only
    imported = {a.asname: (n.module, a.name) for n in tree.body if isinstance(n, ast.ImportFrom) for a in n.names}
    assert imported["BASH_CAPPED"] == ("lib.allowlist", "COMMAND_TOOLS")  # the one definition of the set
    assert _set_literal(next(n.value for n in ast.parse((GATE.parent / "lib" / "allowlist.py").read_text()).body
                             if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "COMMAND_TOOLS")) \
        == {"Bash", "Monitor"}
    assert sets["PERMANENTLY_BLOCKED"] == {"EnterPlanMode", "ExitPlanMode"}
    line = next(ln for ln in (ROOT / "CLAUDE.md").read_text().splitlines() if ln.startswith("- Always allowed:"))
    head = line.split(".", 1)[0].replace("- Always allowed:", "")
    plain, _, read_only_part = head.partition(", and the read-only ")
    named = set(plain.replace("`", "").replace(" ", "").split(","))
    named_read_only = set(read_only_part.replace("`", "").replace(" ", "").split(","))
    assert named == expected, named ^ expected
    assert named_read_only == read_only, named_read_only ^ read_only
    assert named | named_read_only == sets["ALWAYS_ALLOWED"] | sets["READ_ONLY_ALLOWED"]
