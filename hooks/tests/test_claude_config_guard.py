"""hooks/pretool-claude-config-guard.py: the one write it lets through without the sentinel (P1c X4 (b)).

/dev-command develops project slash commands, so its dev writes the command file the cycle asks
for: a subagent whose own dispatch (an Agent call of subagent_type dev whose prompt carries an
obligation of role dev) lies in the span a human-typed /dev-command opened may Write or Edit
<project>/.claude/commands/<name>.md. Every other refusal stays as it was: the main agent, another
role, a /dev span, a span no human typed, a newer span, another path or tool, the harness home's
commands, a link out of the folder.

Each case runs the real hook as a subprocess on a transcript store shaped as the CLI keeps it: the
session's typed commands and Agent calls, each child's first record (its prompt) and the meta
naming its call.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-claude-config-guard.py"
TASK = "20261101-101010"
BLOCK = "BLOCKED: claude config guard"
CMD = ".claude/commands/test.md"


def _prompt(role: str, *, block: bool = True) -> str:
    doc = {"task_id": TASK, "role": role, "pipeline": "dev-command", "profile": "singular",
           "dispatched_at": "2026-11-01T10:10:10Z",
           "artifacts": [{"kind": "json", "path": f"docs/dev/{role}-report-{TASK}.json",
                          "schema": f"{role}-report.v2", "identity": {"task_id": TASK}}]}
    text = f"You are the {role} subagent.\n"
    return text + (f'<obligation v="1">\n{json.dumps(doc)}\n</obligation>\n' if block else "")


class Session:
    def __init__(self, tmp_path: Path):
        self.project = tmp_path / "proj"
        (self.project / ".claude" / "commands").mkdir(parents=True)
        (self.project / ".claude" / "hooks").mkdir(parents=True)
        self.home = tmp_path / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.root = tmp_path / "projects"
        self.sid = "sess-" + uuid.uuid4().hex[:8]
        self.transcript = self.root / f"{self.sid}.jsonl"
        self.subagents = self.root / self.sid / "subagents"
        self.subagents.mkdir(parents=True)
        self.transcript.write_text("")
        self.tmp = tmp_path

    def _append(self, record: dict) -> None:
        with self.transcript.open("a") as fh:
            fh.write(json.dumps(record) + "\n")

    def command(self, name: str, **marks) -> None:
        """A slash command record; typed by the human unless `marks` say otherwise (isMeta: a Skill expansion)."""
        self._append({"type": "user", **marks, "message": {"role": "user", "content":
                      f"<command-message>{name} is running…</command-message>\n"
                      f"<command-name>/{name}</command-name>\n<command-args>add a test command</command-args>"}})

    def dispatch(self, prompt: str, subagent_type: str, meta: bool = True) -> str:
        call_id = "toolu_" + uuid.uuid4().hex[:20]
        self._append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": call_id, "name": "Agent",
             "input": {"description": "d", "prompt": prompt, "subagent_type": subagent_type}}]}})
        agent_id = "a" + uuid.uuid4().hex[:16]
        (self.subagents / f"agent-{agent_id}.jsonl").write_text(
            json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
        if meta:
            (self.subagents / f"agent-{agent_id}.meta.json").write_text(
                json.dumps({"agentType": subagent_type, "toolUseId": call_id}))
        return agent_id

    def run(self, tool: str, tool_input: dict, agent: tuple | None = None, env: dict | None = None):
        payload = {"session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(self.project),
                   "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
        if agent:
            payload.update(agent_id=agent[0], agent_type=agent[1])
        run_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        run_env.update({"HOME": str(self.home), "CLAUDE_PROJECT_DIR": str(self.project),
                        "PYTHONDONTWRITEBYTECODE": "1"}, **(env or {}))
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                              text=True, cwd=str(self.project), env=run_env, timeout=30)

    def write(self, rel: str = CMD, agent: tuple | None = None, tool: str = "Write", **kw):
        path = rel if os.path.isabs(rel) else str(self.project / rel)
        args = {"file_path": path, "content": "x"} if tool == "Write" else \
            {"file_path": path, "old_string": "a", "new_string": "b"}
        return self.run(tool, args, agent, **kw)


def _blocked(proc, kind: str = "commands") -> None:
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    assert f"{BLOCK}: agent" in proc.stderr and f"to .claude/{kind}/" in proc.stderr, proc.stderr


@pytest.fixture()
def cycle(tmp_path):
    """A human-typed /dev-command: BA, the dev that writes the command, QA."""
    s = Session(tmp_path)
    s.command("dev-command")
    s.ba = (s.dispatch(_prompt("ba"), "ba"), "ba")
    s.dev = (s.dispatch(_prompt("dev"), "dev"), "dev")
    s.qa = (s.dispatch(_prompt("qa"), "qa"), "qa")
    return s


def test_the_dev_of_a_typed_dev_command_writes_the_project_command_file(cycle):
    for tool in ("Write", "Edit", "MultiEdit"):
        proc = cycle.write(agent=cycle.dev, tool=tool)
        assert proc.returncode == 0, (tool, proc.stderr)
    assert cycle.write(".claude/commands/other-name.md", agent=cycle.dev).returncode == 0


def test_every_other_caller_is_refused(cycle):
    _blocked(cycle.write())                       # the main agent
    _blocked(cycle.write(agent=cycle.qa))         # another role of the same cycle
    _blocked(cycle.write(agent=cycle.ba))
    # a dev-typed agent whose prompt carries no obligation, or one of another role
    _blocked(cycle.write(agent=(cycle.dispatch(_prompt("dev", block=False), "dev"), "dev")))
    _blocked(cycle.write(agent=(cycle.dispatch(_prompt("qa"), "dev"), "dev")))
    # a dev obligation dispatched as another subagent type
    _blocked(cycle.write(agent=(cycle.dispatch(_prompt("dev"), "general-purpose"), "general-purpose")))
    # a dev whose meta the CLI did not write: its dispatch is unknown
    _blocked(cycle.write(agent=(cycle.dispatch(_prompt("dev"), "dev", meta=False), "dev")))
    # an agent id no dispatch started
    _blocked(cycle.write(agent=("a" + uuid.uuid4().hex[:16], "dev")))


def test_every_other_path_and_tool_is_refused(cycle, tmp_path):
    _blocked(cycle.write(".claude/hooks/x.py", agent=cycle.dev), "hooks")
    _blocked(cycle.write(".claude/hooks/x.md", agent=cycle.dev), "hooks")
    _blocked(cycle.write(".claude/commands/sub/x.md", agent=cycle.dev))
    _blocked(cycle.write(".claude/commands/x.sh", agent=cycle.dev))
    _blocked(cycle.write(str(tmp_path / "elsewhere" / ".claude" / "commands" / "x.md"), agent=cycle.dev))
    # a link in the commands folder to a file outside it
    (cycle.project / ".claude" / "hooks" / "evil.md").write_text("x")
    os.symlink(cycle.project / ".claude" / "hooks" / "evil.md", cycle.project / ".claude" / "commands" / "link.md")
    _blocked(cycle.write(".claude/commands/link.md", agent=cycle.dev))
    proc = cycle.run("Bash", {"command": f"echo x > {CMD}"}, cycle.dev)
    assert proc.returncode == 2 and f"{BLOCK}: agent Bash write to .claude/commands/" in proc.stderr, proc.stderr
    # the project is the harness home's parent: its .claude/commands is the harness's own
    _blocked(cycle.write(agent=cycle.dev, env={"CLAUDE_HOME": str(cycle.project / ".claude")}))


def test_a_span_no_human_typed_or_another_command_is_refused(tmp_path):
    s = Session(tmp_path)
    s.command("dev")
    dev = (s.dispatch(_prompt("dev"), "dev"), "dev")
    _blocked(s.write(agent=dev))                  # /dev's dev
    s.command("dev-command", isMeta=True)         # a Skill expansion opens no span
    dev = (s.dispatch(_prompt("dev"), "dev"), "dev")
    _blocked(s.write(agent=dev))
    s.command("dev-command")
    dev = (s.dispatch(_prompt("dev"), "dev"), "dev")
    assert s.write(agent=dev).returncode == 0
    s.command("dev")                              # a newer typed command: the earlier span's dev is out
    _blocked(s.write(agent=dev))


def test_the_sentinel_still_lets_everything_through(cycle):
    (cycle.project / ".claude" / ".hook-refactor-allow").write_text("")
    assert cycle.write().returncode == 0
    assert cycle.write(".claude/hooks/x.py").returncode == 0
