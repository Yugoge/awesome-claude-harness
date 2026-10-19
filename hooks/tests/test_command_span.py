"""Tests for hooks/lib/command_span.py -- phase P1 (TC-4, acceptance 11).

The span is the records after the latest human-typed harness command outside
stop_contract.CONTROL_COMMANDS. Fixtures use CLI 2.1.303 record shapes only:
leading queue-operation records, attachment records, typed slash commands in
the <command-name> form followed by their isMeta body record, Skill-tool
expansions (isMeta + turnCompanion + sourceToolUseID, as captured live), and
assistant tool_use / user tool_result pairs.

Run with: python3 -m pytest hooks/tests/test_command_span.py -v
"""

import json
import os
import re
import sys
from pathlib import Path

# Add repo root to path so we can import hooks.lib.command_span as a module,
# matching hooks/tests/test_obligation.py's convention.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from hooks.lib import command_span  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_ID = "c41e9a07-2b6d-4e58-8f13-6d0a9b7e2c35"


class _Transcript:
    """A main-session transcript in CLI 2.1.303 record shapes. Every add
    returns the record's 1-based line number."""

    def __init__(self):
        self.records = []
        self._tool_ids = 0

    def _envelope(self, record_type, **fields):
        index = len(self.records) + 1
        record = {
            "parentUuid": f"uuid-{index - 1:04d}" if index > 1 else None,
            "isSidechain": False,
            "type": record_type,
            "uuid": f"uuid-{index:04d}",
            "timestamp": f"2026-10-19T12:{index // 60 % 60:02d}:{index % 60:02d}.000Z",
            "userType": "external",
            "entrypoint": "cli",
            "cwd": "/opt/demo/toyproj",
            "sessionId": SESSION_ID,
            "version": "2.1.303",
            "gitBranch": "master",
        }
        record.update(fields)
        return record

    def add(self, record):
        self.records.append(record)
        return len(self.records)

    def queue_operations(self, content="queued prompt"):
        self.add({"type": "queue-operation", "operation": "enqueue",
                  "timestamp": "2026-10-19T11:59:58.000Z",
                  "sessionId": SESSION_ID, "content": content})
        return self.add({"type": "queue-operation", "operation": "dequeue",
                         "timestamp": "2026-10-19T11:59:59.000Z",
                         "sessionId": SESSION_ID})

    def attachment(self, text="reminder"):
        return self.add(self._envelope(
            "attachment",
            attachment={"type": "total_tokens_reminder", "text": text},
            rendered=[{"content": text}], renderedRole="user",
        ))

    def typed(self, content, **fields):
        """A prompt the human typed."""
        line = len(self.records) + 1
        return self.add(self._envelope(
            "user", promptId=f"prompt-{line:04d}",
            message={"role": "user", "content": content},
            permissionMode="default", origin={"kind": "human"},
            promptSource="sdk", turnOrigin="human", **fields,
        ))

    def meta(self, text):
        """An isMeta user record (a typed command's expanded body)."""
        return self.add(self._envelope(
            "user", isMeta=True,
            message={"role": "user", "content": [{"type": "text", "text": text}]},
        ))

    def scheduled(self, content, is_meta=True):
        """A prompt a scheduled task (CronCreate) fired, as measured on CLI
        2.1.303: an enqueue queue-operation, then a user record with string
        content, isMeta true, turnOrigin "scheduled", promptSource "system",
        queueSkipSlashCommands/queueSkipAttachments true and no origin."""
        self.add({"type": "queue-operation", "operation": "enqueue",
                  "timestamp": "2026-10-19T12:23:00.000Z",
                  "sessionId": SESSION_ID, "content": content})
        line = len(self.records) + 1
        fields = {"isMeta": True} if is_meta else {}
        return self.add(self._envelope(
            "user", promptId=f"prompt-{line:04d}",
            message={"role": "user", "content": content},
            permissionMode="default", promptSource="system",
            queueSkipSlashCommands=True, turnOrigin="scheduled",
            turnPosition={"promptIndex": 1, "turnIndex": 0},
            queueSkipAttachments=True, **fields,
        ))

    def command(self, name, args=""):
        """A typed slash command and the isMeta body record after it."""
        line = self.typed(
            f"<command-message>{name}</command-message>\n"
            f"<command-name>/{name}</command-name>\n"
            f"<command-args>{args}</command-args>"
        )
        self.meta(f"# /{name}\nCommand body for {name}.")
        return line

    def assistant(self, content):
        return self.add(self._envelope(
            "assistant", requestId=f"req_{len(self.records) + 1:04d}",
            message={"model": "claude-opus-5-5", "type": "message",
                     "role": "assistant", "content": content,
                     "stop_reason": "end_turn"},
        ))

    def text(self, text):
        return self.assistant([{"type": "text", "text": text}])

    def tool_use(self, name, tool_input):
        self._tool_ids += 1
        tool_use_id = f"toolu_{self._tool_ids:04d}"
        self.assistant([{"type": "tool_use", "id": tool_use_id, "name": name,
                         "input": tool_input, "caller": {"type": "direct"}}])
        return tool_use_id

    def tool_result(self, tool_use_id, content="ok", is_error=False):
        block = {"type": "tool_result", "tool_use_id": tool_use_id,
                 "content": content}
        if is_error:
            block["is_error"] = True
        return self.add(self._envelope(
            "user",
            message={"role": "user", "content": [block]},
            toolUseResult=("Error: " + content) if is_error else {"stdout": content},
            sourceToolAssistantUUID=f"uuid-{len(self.records):04d}",
        ))

    def tool(self, name, tool_input, result="ok", is_error=False):
        """A tool_use and (unless result is None) its tool_result."""
        tool_use_id = self.tool_use(name, tool_input)
        if result is not None:
            self.tool_result(tool_use_id, result, is_error=is_error)
        return tool_use_id

    def skill(self, skill, text):
        """A Skill tool call, its result and the expansion record it adds."""
        tool_use_id = self.tool_use("Skill", {"skill": skill, "args": ""})
        self.add(self._envelope(
            "user",
            message={"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": tool_use_id,
                "content": f"Launching skill: {skill}"}]},
            toolUseResult={"success": True, "commandName": skill},
            sourceToolAssistantUUID=f"uuid-{len(self.records):04d}",
        ))
        return self.add(self._envelope(
            "user", isMeta=True, turnCompanion=True,
            sourceToolUseID=tool_use_id,
            message={"role": "user", "content": [{"type": "text", "text": text}]},
        ))

    def write(self, path):
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in self.records),
            encoding="utf-8",
        )
        return path


DEV_TEXT = (
    "<command-message>dev</command-message>\n"
    "<command-name>/dev</command-name>\n"
    "<command-args>fix the bug</command-args>"
)


# --------------------------------------------------------------------------
# Opening a span
# --------------------------------------------------------------------------

def test_typed_dev_opens_span(tmp_path):
    tx = _Transcript()
    tx.queue_operations()
    tx.attachment()
    start = tx.typed(DEV_TEXT)
    tx.meta("# /dev\nCommand body.")
    span = command_span.active_span(tx.write(tmp_path / "tag.jsonl"))
    assert span is not None
    assert (span.command, span.args, span.start_line) == ("dev", "fix the bug", start)

    plain_form = _Transcript()
    start = plain_form.typed("/dev fix the bug")
    span = command_span.active_span(plain_form.write(tmp_path / "plain.jsonl"))
    assert (span.command, span.args, span.start_line) == ("dev", "fix the bug", start)


def test_dev_text_in_non_human_records_does_not_open(tmp_path):
    variants = {}

    skill = _Transcript()
    skill.skill("dev", DEV_TEXT)
    skill.skill("dev", "/dev fix the bug")
    variants["skill_expansion"] = skill

    meta = _Transcript()
    meta.meta(DEV_TEXT)
    meta.meta("/dev fix the bug")
    variants["is_meta"] = meta

    result = _Transcript()
    tool_use_id = result.tool_use("Read", {"file_path": "/opt/demo/toyproj/notes.md"})
    result.tool_result(tool_use_id, DEV_TEXT)
    tool_use_id = result.tool_use("Bash", {"command": "cat notes"})
    result.tool_result(tool_use_id, "/dev fix the bug")
    variants["tool_result"] = result

    for is_meta in (True, False):  # either marker alone keeps it out
        scheduled = _Transcript()
        scheduled.scheduled(DEV_TEXT, is_meta=is_meta)
        scheduled.scheduled("/dev fix the bug", is_meta=is_meta)
        variants[f"scheduled_prompt_is_meta_{is_meta}"] = scheduled

    for name, tx in variants.items():
        assert command_span.active_span(tx.write(tmp_path / f"{name}.jsonl")) is None, name

    # Nor does it replace a span a typed command opened.
    for name in variants:
        tx = _Transcript()
        start = tx.command("close")
        if name == "skill_expansion":
            tx.skill("dev", DEV_TEXT)
        elif name == "is_meta":
            tx.meta(DEV_TEXT)
        elif name.startswith("scheduled_prompt"):
            tx.scheduled(DEV_TEXT, is_meta=name.endswith("True"))
        else:
            tool_use_id = tx.tool_use("Read", {"file_path": "notes.md"})
            tx.tool_result(tool_use_id, DEV_TEXT)
        span = command_span.active_span(tx.write(tmp_path / f"after-{name}.jsonl"))
        assert (span.command, span.start_line) == ("close", start), name


def test_leading_queue_operation_records_ignored(tmp_path):
    tx = _Transcript()
    tx.queue_operations(content="/close")
    tx.attachment(text="/close")
    start = tx.command("dev", "fix the bug")
    span = command_span.active_span(tx.write(tmp_path / "main.jsonl"))
    assert start == 4
    assert (span.command, span.args, span.start_line) == ("dev", "fix the bug", 4)

    only_queue = _Transcript()
    only_queue.queue_operations(content=DEV_TEXT)
    assert command_span.active_span(only_queue.write(tmp_path / "queue.jsonl")) is None


# --------------------------------------------------------------------------
# Keeping, continuing and replacing a span
# --------------------------------------------------------------------------

def test_allow_keeps_span_and_plain_prompt_continues(tmp_path):
    tx = _Transcript()
    tx.queue_operations()
    start = tx.command("dev", "fix the bug")
    first = tx.tool("Bash", {"command": "git status"})
    tx.command("allow", "git push")
    second = tx.tool("Bash", {"command": "git push"})
    tx.typed("also update the changelog")
    third = tx.tool("Edit", {"file_path": "CHANGELOG.md"})
    span = command_span.active_span(tx.write(tmp_path / "main.jsonl"))
    assert (span.command, span.args, span.start_line) == ("dev", "fix the bug", start)
    assert [use.id for use in span.uses] == [first, second, third]


def test_typed_stop_replaces_and_builtin_model_does_not(tmp_path):
    tx = _Transcript()
    tx.queue_operations()
    start = tx.command("dev-overnight", "")
    before = tx.tool("Bash", {"command": "ls"})
    tx.command("model", "opus")
    tx.typed("/model sonnet")
    path = tx.write(tmp_path / "model.jsonl")
    span = command_span.active_span(path)
    assert (span.command, span.start_line) == ("dev-overnight", start)
    assert [use.id for use in span.uses] == [before]

    stop_line = tx.command("stop")
    after = tx.tool("Bash", {"command": "pwd"})
    span = command_span.active_span(tx.write(tmp_path / "stop.jsonl"))
    assert (span.command, span.args, span.start_line) == ("stop", "", stop_line)
    assert [use.id for use in span.uses] == [after]


def test_active_span_none_for_missing_file_or_no_command(tmp_path):
    assert command_span.active_span(tmp_path / "missing.jsonl") is None
    tx = _Transcript()
    tx.queue_operations()
    tx.typed("please look at the failing test")
    tx.command("allow", "git push")
    tx.command("model", "opus")
    tx.tool("Bash", {"command": "ls"})
    assert command_span.active_span(tx.write(tmp_path / "plain.jsonl")) is None


# --------------------------------------------------------------------------
# Span accessors
# --------------------------------------------------------------------------

def test_calls_attach_tool_results_and_ok(tmp_path):
    tx = _Transcript()
    outside = tx.tool("Bash", {"command": "echo before"})
    tx.command("dev", "x")
    ok_id = tx.tool("Bash", {"command": "pytest -q"}, result="2 passed")
    error_id = tx.tool("Bash", {"command": "false"}, result="exit 1", is_error=True)
    pending_id = tx.tool("Agent", {"subagent_type": "dev", "prompt": "do it"}, result=None)
    read_id = tx.tool("Read", {"file_path": "README.md"})
    span = command_span.active_span(tx.write(tmp_path / "main.jsonl"))

    bash = span.calls("Bash")
    assert [use.id for use in bash] == [ok_id, error_id]
    assert outside not in [use.id for use in span.uses]
    ok_use, error_use = bash
    assert ok_use.result["tool_use_id"] == ok_id
    assert ok_use.result["content"] == "2 passed"
    assert ok_use.ok is True
    assert error_use.result["is_error"] is True
    assert error_use.ok is False
    assert ok_use.input == {"command": "pytest -q"}

    (agent,) = span.calls("Agent")
    assert agent.id == pending_id and agent.result is None and agent.ok is False
    assert [use.id for use in span.calls("Bash", "Agent")] == [ok_id, error_id, pending_id]
    assert [use.id for use in span.calls("Read")] == [read_id]
    assert span.calls("Write") == []


def test_last_todos_returns_last_ok_todowrite(tmp_path):
    def todos(label):
        return [{"content": label, "status": "in_progress", "activeForm": label}]

    tx = _Transcript()
    tx.command("dev", "x")
    tx.tool("TodoWrite", {"todos": todos("first")})
    tx.tool("TodoWrite", {"todos": todos("second")})
    tx.tool("TodoWrite", {"todos": todos("refused")}, result="hook refused", is_error=True)
    tx.tool("TodoWrite", {"todos": todos("pending")}, result=None)
    span = command_span.active_span(tx.write(tmp_path / "main.jsonl"))
    assert span.last_todos() == todos("second")

    none = _Transcript()
    none.command("dev", "x")
    none.tool("TodoWrite", {"todos": todos("refused")}, result="refused", is_error=True)
    none.tool("Bash", {"command": "ls"})
    span = command_span.active_span(none.write(tmp_path / "none.jsonl"))
    assert span.last_todos() is None


def test_final_text_prefers_payload_last_assistant_message(tmp_path):
    tx = _Transcript()
    tx.text("before the span")
    tx.command("dev", "x")
    tx.text("first answer")
    tx.tool("Bash", {"command": "ls"})
    tx.text("final answer from the transcript")
    span = command_span.active_span(tx.write(tmp_path / "main.jsonl"))
    assert span.last_text == "final answer from the transcript"
    assert span.final_text({"last_assistant_message": "final answer from the payload"}) == (
        "final answer from the payload"
    )
    for payload in ({}, {"last_assistant_message": "   "},
                    {"last_assistant_message": None}, None):
        assert span.final_text(payload) == "final answer from the transcript", payload


# --------------------------------------------------------------------------
# D4c: no error, cancellation or pause grammar in the span libraries
# --------------------------------------------------------------------------

def test_span_libraries_read_no_error_or_pause_markers():
    forbidden = re.compile(r"isApiErrorMessage|interrupt|AWAITING_INPUT|PAUSE")
    for name in ("command_span.py", "stop_contract.py"):
        path = REPO_ROOT / "hooks" / "lib" / name
        hits = [
            (number, line)
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            )
            if forbidden.search(line)
        ]
        assert hits == [], (name, hits)
