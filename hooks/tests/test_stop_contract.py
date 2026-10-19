"""Tests for hooks/lib/stop_contract.py -- phase P1 (TC-4, acceptance 11).

Pins the command tuples, the human-typed prompt rule (is_human_prompt), the
slash-command recogniser and active_command over CLI-shaped transcripts
(CLI 2.1.303 record envelopes: queue-operation and attachment records, typed
prompts with origin kind "human", Skill-tool expansions carrying isMeta and
sourceToolUseID, tool results carrying toolUseResult).

Run with: python3 -m pytest hooks/tests/test_stop_contract.py -v
"""

import json
import os
import sys
from pathlib import Path

# Add repo root to path so we can import hooks.lib.stop_contract as a module,
# matching hooks/tests/test_obligation.py's convention.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from hooks.lib import stop_contract  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_ID = "8b2f4c1d-6a3e-4f70-9d12-3c5e7a9b0f14"


# --------------------------------------------------------------------------
# CLI-shaped record builders (CLI 2.1.303 envelope)
# --------------------------------------------------------------------------

def _envelope(record_type, index=1, **fields):
    record = {
        "parentUuid": f"uuid-{index - 1:04d}" if index else None,
        "isSidechain": False,
        "type": record_type,
        "uuid": f"uuid-{index:04d}",
        "timestamp": f"2026-10-19T11:00:{index % 60:02d}.000Z",
        "userType": "external",
        "entrypoint": "cli",
        "cwd": "/opt/demo/toyproj",
        "sessionId": SESSION_ID,
        "version": "2.1.303",
        "gitBranch": "master",
    }
    record.update(fields)
    return record


def _typed(content, index=1, **fields):
    """A prompt the human typed (string or content-block list)."""
    return _envelope(
        "user", index,
        promptId=f"prompt-{index:04d}",
        message={"role": "user", "content": content},
        permissionMode="default",
        origin={"kind": "human"},
        promptSource="sdk",
        turnOrigin="human",
        **fields,
    )


def _command_text(name, args=""):
    return (
        f"<command-message>{name}</command-message>\n"
        f"<command-name>/{name}</command-name>\n"
        f"<command-args>{args}</command-args>"
    )


def _command_body(index, text="# Command body\nFollow the steps."):
    """The isMeta record the CLI writes after a typed slash command."""
    return _envelope(
        "user", index, isMeta=True,
        promptId=f"prompt-{index - 1:04d}",
        message={"role": "user", "content": [{"type": "text", "text": text}]},
    )


def _skill_expansion(text, index=1, tool_use_id="toolu_skill_0001"):
    """The user record a Skill tool call produces (isMeta + sourceToolUseID)."""
    return _envelope(
        "user", index, isMeta=True, turnCompanion=True,
        promptId="prompt-0001",
        sourceToolUseID=tool_use_id,
        message={"role": "user", "content": [{"type": "text", "text": text}]},
    )


def _tool_result(tool_use_id, content, index=1, is_error=False):
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if is_error:
        block["is_error"] = True
    return _envelope(
        "user", index,
        promptId="prompt-0001",
        message={"role": "user", "content": [block]},
        toolUseResult={"success": not is_error, "commandName": "dev"},
        sourceToolAssistantUUID=f"uuid-{index - 1:04d}",
    )


def _assistant(content, index=1):
    return _envelope(
        "assistant", index, requestId=f"req_{index:04d}",
        message={
            "model": "claude-opus-5-5", "id": f"msg_{index:04d}",
            "type": "message", "role": "assistant", "content": content,
            "stop_reason": "end_turn",
        },
    )


def _skill_call(skill, args, index=1, tool_use_id="toolu_skill_0001"):
    return _assistant([{
        "type": "tool_use", "id": tool_use_id, "name": "Skill",
        "input": {"skill": skill, "args": args}, "caller": {"type": "direct"},
    }], index)


def _queue_operations():
    return [
        {"type": "queue-operation", "operation": "enqueue",
         "timestamp": "2026-10-19T10:59:58.000Z", "sessionId": SESSION_ID,
         "content": "queued prompt"},
        {"type": "queue-operation", "operation": "dequeue",
         "timestamp": "2026-10-19T10:59:59.000Z", "sessionId": SESSION_ID},
    ]


def _attachment(index=1, text="/dev from an attachment"):
    return _envelope(
        "attachment", index,
        attachment={"type": "total_tokens_reminder", "text": text},
        rendered=[{"content": text}], renderedRole="user",
    )


def _write(path, records):
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------
# Command tuples
# --------------------------------------------------------------------------

def test_gated_and_control_command_tuples():
    assert stop_contract.GATED_COMMANDS == (
        "do", "dev", "redev", "dev-command", "dev-overnight",
        "close", "commit", "merge", "push",
    )
    assert stop_contract.CONTROL_COMMANDS == (
        "allow", "restart", "checkpoint", "tickets",
    )
    assert not set(stop_contract.GATED_COMMANDS) & set(stop_contract.CONTROL_COMMANDS)


def test_harness_commands_are_command_stems_without_index_readme():
    commands = stop_contract.harness_commands()
    stems = {p.stem for p in (REPO_ROOT / "commands").glob("*.md")}
    assert commands == stems - {"INDEX", "README"}
    assert "INDEX" not in commands and "README" not in commands
    assert "stop" in commands and "model" not in commands
    assert set(stop_contract.GATED_COMMANDS) <= commands
    assert set(stop_contract.CONTROL_COMMANDS) <= commands


# --------------------------------------------------------------------------
# is_human_prompt
# --------------------------------------------------------------------------

def test_is_human_prompt_typed_string_and_text_blocks():
    assert stop_contract.is_human_prompt(_typed("please fix the build"))
    assert stop_contract.prompt_text(_typed("please fix the build")) == "please fix the build"
    blocks = _typed([
        {"type": "text", "text": "part one, "},
        {"type": "text", "text": "part two"},
    ])
    assert stop_contract.is_human_prompt(blocks)
    assert stop_contract.prompt_text(blocks) == "part one, part two"
    # origin and turnOrigin absent still count as typed.
    bare = _typed(_command_text("dev", "x"))
    del bare["origin"], bare["turnOrigin"]
    assert stop_contract.is_human_prompt(bare)


def test_is_human_prompt_false_for_non_human_markers():
    text = _command_text("dev", "x")
    is_meta = _typed(text, isMeta=True)
    sidechain = _typed(text)
    sidechain["isSidechain"] = True
    skill = _skill_expansion(text)
    # Each marker alone is enough (the captured Skill record carries both).
    source_only = _skill_expansion(text)
    del source_only["isMeta"], source_only["turnCompanion"]
    tool_use_result = _typed(text, toolUseResult={"success": True})
    tool_result = _tool_result("toolu_0001", text)
    mixed = _typed([
        {"type": "text", "text": text},
        {"type": "tool_result", "tool_use_id": "toolu_0001", "content": "ok"},
    ])
    peer = _typed(text)
    peer["origin"] = {"kind": "peer"}
    scheduled = _typed(text)
    scheduled["origin"] = {"kind": "scheduled"}
    turn_origin = _typed(text)
    turn_origin["turnOrigin"] = "peer"
    assistant = _assistant([{"type": "text", "text": text}])
    queue = _queue_operations()[0]
    queue["content"] = text
    attachment = _attachment(text=text)
    cases = {
        "isMeta": is_meta,
        "isSidechain": sidechain,
        "skill_expansion": skill,
        "sourceToolUseID": source_only,
        "toolUseResult": tool_use_result,
        "tool_result": tool_result,
        "text_and_tool_result": mixed,
        "origin_peer": peer,
        "origin_scheduled": scheduled,
        "turnOrigin_peer": turn_origin,
        "assistant": assistant,
        "queue-operation": queue,
        "attachment": attachment,
    }
    for name, record in cases.items():
        assert stop_contract.is_human_prompt(record) is False, name
        assert stop_contract.prompt_text(record) is None, name
    assert stop_contract.is_human_prompt(None) is False
    assert stop_contract.is_human_prompt("plain string") is False


# --------------------------------------------------------------------------
# slash_command
# --------------------------------------------------------------------------

def test_slash_command_forms():
    assert stop_contract.slash_command("/dev x") == ("dev", "x")
    assert stop_contract.slash_command("  /dev   fix the bug  ") == ("dev", "fix the bug")
    assert stop_contract.slash_command("/dev") == ("dev", "")
    assert stop_contract.slash_command(
        "<command-name>/dev</command-name>...<command-args>x</command-args>"
    ) == ("dev", "x")
    assert stop_contract.slash_command(_command_text("dev-overnight", " run all ")) == (
        "dev-overnight", "run all",
    )
    assert stop_contract.slash_command("<command-name>/model</command-name>") == ("model", "")
    assert stop_contract.slash_command("//x") is None
    assert stop_contract.slash_command("/") is None
    assert stop_contract.slash_command("please run the dev cycle") is None
    assert stop_contract.slash_command("") is None
    # Any whitespace ends the command name; the CLI's tags open the record.
    assert stop_contract.slash_command("/dev\nfix the bug") == ("dev", "fix the bug")
    assert stop_contract.slash_command("/ dev") is None
    assert stop_contract.slash_command("see <command-name>/dev</command-name> in the log") is None


def test_span_opener_harness_commands_outside_control():
    commands = stop_contract.harness_commands()
    assert stop_contract.span_opener(_typed(_command_text("dev", "x")), commands) == ("dev", "x")
    assert stop_contract.span_opener(_typed("/stop now"), commands) == ("stop", "now")
    assert stop_contract.span_opener(_typed(_command_text("allow", "git push")), commands) is None
    assert stop_contract.span_opener(_typed(_command_text("model", "opus")), commands) is None
    assert stop_contract.span_opener(_typed("plain prompt"), commands) is None
    assert stop_contract.span_opener(_skill_expansion(_command_text("dev", "x")), commands) is None


# --------------------------------------------------------------------------
# active_command
# --------------------------------------------------------------------------

def test_active_command_latest_typed_harness_command(tmp_path):
    transcript = _write(tmp_path / "main.jsonl", _queue_operations() + [
        _attachment(1),
        _typed(_command_text("dev", "fix the bug"), 2),
        _command_body(3),
        _assistant([{"type": "text", "text": "Starting."}], 4),
        _typed("and also the docs", 5),
    ])
    assert stop_contract.active_command(transcript) == "dev"


def test_active_command_allow_and_builtin_do_not_replace(tmp_path):
    transcript = _write(tmp_path / "main.jsonl", _queue_operations() + [
        _typed(_command_text("dev", "fix the bug"), 1),
        _command_body(2),
        _typed(_command_text("allow", "git push"), 3),
        _command_body(4),
        _typed(_command_text("model", "opus"), 5),
        _typed("/model sonnet", 6),
    ])
    assert stop_contract.active_command(transcript) == "dev"


def test_active_command_typed_stop_replaces(tmp_path):
    transcript = _write(tmp_path / "main.jsonl", _queue_operations() + [
        _typed(_command_text("dev-overnight", ""), 1),
        _command_body(2),
        _typed(_command_text("stop", ""), 3),
        _command_body(4),
        _typed(_command_text("allow", "git push"), 5),
    ])
    assert stop_contract.active_command(transcript) == "stop"


def test_active_command_ignores_non_human_records(tmp_path):
    text = _command_text("close", "")
    transcript = _write(tmp_path / "main.jsonl", _queue_operations() + [
        _typed(_command_text("dev", "x"), 1),
        _command_body(2, text=text),
        _skill_call("close", "", 3),
        _tool_result("toolu_skill_0001", "Launching skill: close", 4),
        _skill_expansion(text, 5),
        _attachment(6, text=text),
        _assistant([{"type": "text", "text": "/close"}], 7),
    ])
    assert stop_contract.active_command(transcript) == "dev"


def test_active_command_none_without_command_or_file(tmp_path):
    assert stop_contract.active_command(tmp_path / "missing.jsonl") is None
    plain = _write(tmp_path / "plain.jsonl", _queue_operations() + [
        _attachment(1),
        _typed("please look at the failing test", 2),
        _typed(_command_text("allow", "git push"), 3),
        _typed(_command_text("model", "opus"), 4),
        _skill_expansion(_command_text("dev", "x"), 5),
        _assistant([{"type": "text", "text": "Looking."}], 6),
    ])
    assert stop_contract.active_command(plain) is None
    empty = _write(tmp_path / "empty.jsonl", [])
    assert stop_contract.active_command(empty) is None
