"""P9-41: the orchestrator gate's refusals in a span whose command text is older than the harness's (P1b A17, D15).

P9 reworded the gate's refusals (the Bash limit's and the non-whitelisted limit's first line, the
permanent block's three lines). A session that took up origin/master's command text before the
update keeps that text, and P1b's acceptance 17 asks it to meet no refusal the base does not show at
the same hook, step and refusal text. So, as pretool-todo-validate.py does for Gate 4 (c8225f48), the
gate reads the text the session loaded (command_span.Span.body): when it is not commands/<command>.md
as it is now, the refusal is printed in origin/master's (2acc29b's) wording. A span on the harness's own
text keeps the current wording. The rule and the counts are the same in both.

The BASE_* lines below are 2acc29b's hooks/pretool-orchestrator-gate.py output, byte for byte
(`git show 2acc29b:hooks/pretool-orchestrator-gate.py`, block_streak and block_permanent).
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
GATE = ROOT / "hooks" / "pretool-orchestrator-gate.py"

BASE_BASH = ("[Orchestrator Gate] BLOCKED: Bash used consecutively beyond limit (6/5).\n"
             "Delegate to a subagent (Agent tool) or ask the user to run /do to unlock.\n")
BASE_WRITE = ("[Orchestrator Gate] BLOCKED: Write used consecutively beyond limit (2/1).\n"
              "Delegate to a subagent (Agent tool) or ask the user to run /do to unlock.\n")
BASE_PERMANENT = ("[Orchestrator Gate] Permanently blocked: EnterPlanMode\n"
                  "Delegate to subagents (Agent tool) or run /do to unlock.\n"
                  "Allowed without /do: Agent, AskUserQuestion, Bash, CronCreate, CronDelete, CronList, Glob, "
                  "Grep, Read, ScheduleWakeup, Skill, TodoWrite\n")

CURRENT_BASH = ("[Orchestrator Gate] BLOCKED: Bash used consecutively beyond limit (6/5): Bash counts its calls "
                "since the last Agent dispatch or prompt, any other non-whitelisted tool its calls this turn, "
                "whatever ran between them.\n"
                "Delegate to a subagent (Agent tool) or ask the user to run /do to unlock.\n")
CURRENT_PERMANENT_FIRST = "[Orchestrator Gate] Permanently blocked: EnterPlanMode (/do does not unlock it).\n"

OLD_TEXT = "# /dev\n\nThe text this session took up before the update.\n\nARGUMENTS: {args}"


def _current_text(command: str, args: str) -> str:
    """The isMeta body the CLI records for the harness's own commands/<command>.md."""
    lines = (ROOT / "commands" / f"{command}.md").read_text(encoding="utf-8").split("\n")
    if lines[0].strip() == "---":
        lines = lines[lines.index("---", 1) + 1:]
    text = "\n".join(lines)
    return text.replace("$ARGUMENTS", args) if "$ARGUMENTS" in text else f"{text}\n\nARGUMENTS: {args}"


class Session:
    """A main-session transcript in the CLI's record shapes; each gate run is a subprocess with the
    PreToolUse payload the CLI sends, its HOME, state dir, project and TMPDIR inside tmp_path."""

    def __init__(self, tmp_path: Path):
        self.tmp, self.sid, self.n = tmp_path, str(uuid.uuid4()), 0
        self.home, self.project, self.state = tmp_path / "home", tmp_path / "project", tmp_path / "state"
        for d in (self.home, self.project / ".claude", self.state, tmp_path / "tmp"):
            d.mkdir(parents=True, exist_ok=True)
        self.transcript = tmp_path / "transcript.jsonl"
        self.transcript.write_text("")

    def add(self, record: dict) -> None:
        self.n += 1
        record = dict(record, uuid=f"uuid-{self.n:04d}", parentUuid=f"uuid-{self.n - 1:04d}" if self.n > 1 else None,
                      isSidechain=False, sessionId=self.sid)
        with self.transcript.open("a") as handle:
            handle.write(json.dumps(record) + "\n")

    def command(self, command: str, args: str, text: str | None) -> None:
        """A typed /command, then (unless ``text`` is None) the isMeta record of the text it loaded."""
        self.add({"type": "user", "message": {"role": "user", "content":
                  f"<command-message>{command} is running…</command-message>\n<command-name>/{command}</command-name>\n"
                  f"<command-args>{args}</command-args>"}})
        if text is not None:
            self.add({"type": "user", "isMeta": True,
                      "message": {"role": "user", "content": [{"type": "text", "text": text}]}})

    def gate(self, tool: str, tool_input: dict | None = None) -> subprocess.CompletedProcess:
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
               "CLAUDE_STATE_DIR": str(self.state), "TMPDIR": str(self.tmp / "tmp"),
               "CLAUDE_PROJECT_DIR": str(self.project), "GIT_CEILING_DIRECTORIES": str(self.tmp),
               "PYTHONDONTWRITEBYTECODE": "1"}
        body = {"session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(self.project),
                "hook_event_name": "PreToolUse", "permission_mode": "default", "tool_name": tool,
                "tool_input": tool_input or {}}
        return subprocess.run([sys.executable, str(GATE)], input=json.dumps(body), capture_output=True,
                              text=True, env=env, cwd=self.project, timeout=60)

    def bash_limit(self) -> subprocess.CompletedProcess:
        for i in range(5):
            assert self.gate("Bash", {"command": f"echo {i}"}).returncode == 0
        return self.gate("Bash", {"command": "echo 5"})

    def write_limit(self) -> subprocess.CompletedProcess:
        assert self.gate("Write", {"file_path": str(self.project / "a.md"), "content": "x"}).returncode == 0
        return self.gate("Write", {"file_path": str(self.project / "b.md"), "content": "x"})


@pytest.fixture
def in_flight(tmp_path):
    s = Session(tmp_path)
    s.command("dev", "fix the thing", OLD_TEXT.format(args="fix the thing"))
    return s


@pytest.fixture
def current(tmp_path):
    s = Session(tmp_path)
    s.command("dev", "fix the thing", _current_text("dev", "fix the thing"))
    return s


def test_in_flight_bash_limit_reads_as_the_base(in_flight):
    out = in_flight.bash_limit()
    assert out.returncode == 2
    assert out.stderr == BASE_BASH


def test_in_flight_non_whitelist_limit_reads_as_the_base(in_flight):
    out = in_flight.write_limit()
    assert out.returncode == 2
    assert out.stderr == BASE_WRITE


def test_in_flight_permanent_block_reads_as_the_base(in_flight):
    out = in_flight.gate("EnterPlanMode")
    assert out.returncode == 2
    assert out.stderr == BASE_PERMANENT


def test_current_text_keeps_the_current_wording(current):
    out = current.bash_limit()
    assert out.returncode == 2 and out.stderr == CURRENT_BASH
    out = current.write_limit()
    assert out.returncode == 2 and out.stderr.startswith(
        "[Orchestrator Gate] BLOCKED: Write used consecutively beyond limit (2/1): Bash counts")
    out = current.gate("EnterPlanMode")
    assert out.returncode == 2 and out.stderr.startswith(CURRENT_PERMANENT_FIRST)


@pytest.mark.parametrize("shape", ["no command span", "no recorded text"])
def test_no_loaded_text_keeps_the_current_wording(tmp_path, shape):
    s = Session(tmp_path)
    if shape == "no command span":
        s.add({"type": "user", "message": {"role": "user", "content": "a plain prompt"}})
    else:
        s.command("dev", "fix the thing", None)
    out = s.bash_limit()
    assert out.returncode == 2 and out.stderr == CURRENT_BASH


def test_in_flight_keeps_the_rule_and_the_counts(in_flight):
    """Only the text differs: five Bash calls pass, an Agent dispatch resets the streak, the sixth
    after five is refused with the same count; a second Write is refused, a third counts on."""
    for _ in range(2):
        for i in range(5):
            assert in_flight.gate("Bash", {"command": f"echo {i}"}).returncode == 0
        assert in_flight.gate("Agent", {"subagent_type": "dev", "prompt": "x"}).returncode == 0
    assert in_flight.bash_limit().stderr == BASE_BASH
    assert in_flight.write_limit().returncode == 2
    third = in_flight.gate("Write", {"file_path": str(in_flight.project / "c.md"), "content": "x"})
    assert third.returncode == 2 and third.stderr == BASE_WRITE.replace("(2/1)", "(3/1)")
