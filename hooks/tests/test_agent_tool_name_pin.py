"""T6: hooks see the subagent tool as "Agent", even when the model calls its old name "Task".

The CLI renamed its subagent tool from Task to Agent and still accepts "Task" as an alias. The
harness keys its dispatch handling on the name a hook receives: the orchestrator gate's whitelist
and its Agent-clear (the Bash-cap reset, hooks/pretool-orchestrator-gate.py), the dispatch gate
and its witness (the 'dispatch-gate' rule of hooks/pretool-launch.py, which selects by exact
tool_name), and the dispatch record (hooks/posttool-launch.py). If a hook ever received "Task"
for a dispatch, all of them would be skipped.

Measured on CLI 2.1.326 (the fixture hooks/tests/fixtures/cli-agent-dispatch-hook-payloads.json):
- a dispatch the model makes as "Agent" reaches PreToolUse and PostToolUse hooks as "Agent";
- a dispatch the model makes as "Task" is recorded in the transcript as "Task", and still reaches
  every hook as "Agent": the CLI resolves the alias to the tool and hands hooks the tool's own
  name. A hook registered with matcher "Task" fires on it too, also with tool_name "Agent".

So the harness keys on "Agent" and nothing more is needed in the hooks; transcript readers already
accept both names (lib/command_span.Span.uses('Agent', 'Task') and the like). These tests pin it:
- the recorded payloads, and the harness's dispatch keys and Bash-cap reset run against them;
- a drift detector over the installed CLI: the real `claude` binary runs against a local stand-in
  for the Messages API that answers with a tool_use named "Task", with logging hooks registered
  in a throwaway HOME. No network and no account: if a future CLI hands hooks "Task", this test
  fails, and the harness must treat "Task" as "Agent" at every site named above. Skipped only
  where no `claude` is installed.

To re-record the fixture, run a real session (claude -p, throwaway HOME, hooks that append their
stdin to a file, registered with no matcher, matcher "Agent" and matcher "Task"), once asking for
an Agent dispatch and once asking the model to emit a tool_use named literally "Task".
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "hooks" / "tests" / "fixtures" / "cli-agent-dispatch-hook-payloads.json"
GATE = ROOT / "hooks" / "pretool-orchestrator-gate.py"
BACKGROUND = ROOT / "hooks" / "pretool-block-background-tasks.py"
CAPPED = "used consecutively beyond limit"
MARKER = "T6-AGENT-NAME-PROBE"


def recorded() -> dict:
    return json.loads(FIXTURE.read_text())


def assert_hooks_saw_agent(payloads: list[dict]) -> None:
    events = {p["hook_event_name"] for p in payloads}
    assert {"PreToolUse", "PostToolUse"} <= events, events
    names = sorted({p["tool_name"] for p in payloads})
    assert names == ["Agent"], (
        f"hooks received tool_name {names} for a subagent dispatch; the harness keys its dispatch "
        "handling on 'Agent' only (orchestrator gate, dispatch gate and witness, Bash-cap reset)")


def _rule_tools(launcher: str, rule: str) -> tuple:
    sys.path.insert(0, str(ROOT / "hooks"))
    try:
        from lib import launch_settings  # the launchers' static table reader
    finally:
        sys.path.pop(0)
    for path, tools, _timeout in launch_settings.rules(str(ROOT), f"hooks/{launcher}"):
        if path == f"pretool-{rule}.py" or path == f"posttool-{rule}.py":
            return tools
    raise AssertionError(f"{launcher} has no Rule {rule!r}")


def _always_allowed() -> set:
    tree = ast.parse(GATE.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "ALWAYS_ALLOWED" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("pretool-orchestrator-gate.py has no ALWAYS_ALLOWED")


def test_recorded_dispatches_reach_hooks_as_agent_even_when_the_model_called_task():
    runs = {run["run"]: run for run in recorded()["runs"]}
    assert runs["agent"]["transcript_tool_use_names"] == ["Agent"]
    assert runs["task-alias"]["transcript_tool_use_names"] == ["Task"]
    for run in runs.values():
        assert_hooks_saw_agent(run["hook_payloads"])
        # a registration with matcher "Task" fired too, and was handed "Agent" as well
        by_matcher = {(p["registration_matcher"], p["hook_event_name"]) for p in run["hook_payloads"]}
        assert {("Task", "PreToolUse"), ("Task", "PostToolUse"), ("Agent", "PreToolUse")} <= by_matcher


def test_the_dispatch_rules_select_the_name_hooks_receive():
    names = {p["tool_name"] for run in recorded()["runs"] for p in run["hook_payloads"]}
    for name in names:
        assert name in _rule_tools("pretool-launch.py", "dispatch-gate")
        assert name in _rule_tools("posttool-launch.py", "dispatch-record")
        assert name in _always_allowed()


class Session:
    def __init__(self, tmp_path: Path):
        self.tmp, self.sid = tmp_path, str(uuid.uuid4())
        self.home, self.project, self.state = tmp_path / "home", tmp_path / "project", tmp_path / "state"
        for d in (self.project / ".claude", self.state, tmp_path / "tmp"):
            d.mkdir(parents=True, exist_ok=True)
        tdir = self.home / ".claude" / "projects" / "-project"
        tdir.mkdir(parents=True)
        self.transcript = tdir / f"{self.sid}.jsonl"
        record = {"type": "user", "message": {"role": "user", "content": "fix the bug"}, "sessionId": self.sid,
                  "version": recorded()["cli_version"]}
        self.transcript.write_text(json.dumps(record) + "\n")

    def run(self, hook: Path, payload: dict) -> subprocess.CompletedProcess:
        body = {**payload, "session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(self.project),
                "tool_use_id": f"toolu_{uuid.uuid4().hex[:20]}"}
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
               "CLAUDE_STATE_DIR": str(self.state), "TMPDIR": str(self.tmp / "tmp"),
               "CLAUDE_PROJECT_DIR": str(self.project), "GIT_CEILING_DIRECTORIES": str(self.tmp),
               "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run([sys.executable, str(hook)], input=json.dumps(body), capture_output=True,
                              text=True, env=env, cwd=self.project, timeout=60)

    def bash(self) -> subprocess.CompletedProcess:
        """A Bash call the cap counts: python3 runs code, so lib/bash_read_only does not prove it read-only
        (a proven read-only command passes uncounted, OB-L03, and would never reach the cap)."""
        return self.run(GATE, {"hook_event_name": "PreToolUse", "permission_mode": "default", "tool_name": "Bash",
                               "tool_input": {"command": "python3 x.py", "description": "probe"}})


def test_the_recorded_task_alias_dispatch_resets_the_bash_cap_and_passes_the_no_background_rule(tmp_path):
    run = next(r for r in recorded()["runs"] if r["run"] == "task-alias")
    pre = next(p for p in run["hook_payloads"]
               if p["hook_event_name"] == "PreToolUse" and p["registration_matcher"] == "*")
    payload = {"hook_event_name": "PreToolUse", "permission_mode": "default",
               "tool_name": pre["tool_name"], "tool_input": pre["tool_input"]}
    s = Session(tmp_path)
    for _ in range(5):
        assert s.bash().returncode == 0
    capped = s.bash()
    assert capped.returncode == 2 and CAPPED in capped.stderr
    dispatched = s.run(GATE, payload)
    assert dispatched.returncode == 0, dispatched.stderr
    assert s.bash().returncode == 0  # the dispatch cleared the streak
    assert s.run(BACKGROUND, payload).returncode == 0
    foreground_unset = {**payload, "tool_input": {k: v for k, v in pre["tool_input"].items() if k != "run_in_background"}}
    assert s.run(BACKGROUND, foreground_unset).returncode == 0  # a background dispatch passes too


class _StandInModel(BaseHTTPRequestHandler):
    """The Messages API as the CLI calls it: one tool_use named "Task" for the marked prompt, text otherwise."""

    served = False

    def log_message(self, *_):
        pass

    def _send(self, ctype: str, body: bytes) -> None:
        self.send_response(200)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send("application/json", b"{}")

    def do_HEAD(self):
        self._send("application/json", b"")

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        try:
            req = json.loads(raw)
        except ValueError:
            req = {}
        if not self.path.startswith("/v1/messages") or "count_tokens" in self.path:
            return self._send("application/json", b'{"input_tokens": 1}')
        tools = {t.get("name") for t in req.get("tools") or [] if isinstance(t, dict)}
        if "Agent" in tools and MARKER in json.dumps(req.get("messages")) and not type(self).served:
            type(self).served = True
            dispatch = {"subagent_type": "general-purpose", "description": "probe", "prompt": "Reply OK.",
                        "run_in_background": False}
            block = [{"type": "content_block_start", "index": 0,
                      "content_block": {"type": "tool_use", "id": "toolu_t6probe0000000000000001", "name": "Task",
                                        "input": {}}},
                     {"type": "content_block_delta", "index": 0,
                      "delta": {"type": "input_json_delta", "partial_json": json.dumps(dispatch)}}]
            stop = "tool_use"
        else:
            block = [{"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                     {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "OK"}}]
            stop = "end_turn"
        if not req.get("stream"):
            return self._send("application/json", json.dumps({
                "id": "msg_t6", "type": "message", "role": "assistant", "model": "stand-in",
                "content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1}}).encode())
        events = [{"type": "message_start", "message": {
            "id": "msg_t6", "type": "message", "role": "assistant", "model": "stand-in", "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}},
            *block, {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
             "usage": {"output_tokens": 1}},
            {"type": "message_stop"}]
        self._send("text/event-stream",
                   "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode())


def test_installed_cli_hands_hooks_agent_when_the_model_calls_task(tmp_path):
    cli = shutil.which("claude")
    if cli is None:
        pytest.skip("no claude CLI installed; the recorded fixture still pins the measured payloads")
    log = tmp_path / "payloads.jsonl"
    logger = tmp_path / "log_hook.py"
    logger.write_text("import json, sys\nrecord = {**json.load(sys.stdin), 'registration': sys.argv[2]}\n"
                      "with open(sys.argv[1], 'a') as f:\n    f.write(json.dumps(record) + '\\n')\n")
    home, project = tmp_path / "home", tmp_path / "project"
    (home / ".claude").mkdir(parents=True)
    project.mkdir()

    def reg(matcher):
        # one command per registration: the CLI runs an identical command once per call
        entry = {"hooks": [{"type": "command", "command": f"{sys.executable} {logger} {log} {matcher or '*'}"}]}
        return {**entry, "matcher": matcher} if matcher else entry

    (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {
        "PreToolUse": [reg(None), reg("Agent"), reg("Task")], "PostToolUse": [reg(None)]}}))
    _StandInModel.served = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StandInModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        env = {"PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": str(tmp_path),
               "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}",
               "ANTHROPIC_API_KEY": "sk-ant-stand-in", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
               "IS_SANDBOX": "1"}  # the CLI refuses bypassPermissions as root without it
        done = subprocess.run([cli, "-p", MARKER, "--permission-mode", "bypassPermissions",
                               "--output-format", "json"], env=env, cwd=project, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=240)
    finally:
        server.shutdown()
    assert done.returncode == 0, done.stderr[-2000:]
    payloads = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    transcripts = list((home / ".claude" / "projects").glob("*/*.jsonl"))
    assert len(transcripts) == 1, transcripts
    names = [b.get("name") for line in transcripts[0].read_text().splitlines()
             for rec in [json.loads(line)] if rec.get("type") == "assistant"
             for b in rec.get("message", {}).get("content") or [] if isinstance(b, dict) and b.get("type") == "tool_use"]
    assert names == ["Task"], f"the stand-in's call was not made as 'Task' (CLI {done.stdout[:300]!r})"
    assert_hooks_saw_agent(payloads)
    fired = sorted((p["hook_event_name"], p["registration"]) for p in payloads)
    assert fired == [("PostToolUse", "*"), ("PreToolUse", "*"), ("PreToolUse", "Agent"), ("PreToolUse", "Task")]
