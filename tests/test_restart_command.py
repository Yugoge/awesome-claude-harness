"""End-to-end unit coverage for the human-only /restart recovery protocol."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS))

from lib import subagent_restart as restart  # noqa: E402


def _record(role: str, content: list[dict]) -> dict:
    return {"type": role, "message": {"role": role, "content": content}}


def _tool_use(
    tool_id: str,
    description: str,
    *,
    agent_type: str = "dev",
    background: bool = False,
) -> dict:
    return {
        "type": "tool_use",
        "id": tool_id,
        "name": "Agent",
        "input": {
            "description": description,
            "subagent_type": agent_type,
            "prompt": f"Do exactly one issue: {description}",
            "run_in_background": background,
        },
    }


def _tool_result(tool_id: str, text: str, *, error: bool = False) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_id,
        "is_error": error,
        "content": [{"type": "text", "text": text}],
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")


def _write_meta(transcript: Path, agent_id: str, tool_id: str, description: str) -> Path:
    subagents = transcript.with_suffix("") / "subagents"
    subagents.mkdir(parents=True, exist_ok=True)
    meta = subagents / f"agent-{agent_id}.meta.json"
    meta.write_text(json.dumps({
        "agentType": "dev",
        "description": description,
        "toolUseId": tool_id,
        "spawnDepth": 1,
    }), encoding="utf-8")
    _write_jsonl(
        subagents / f"agent-{agent_id}.jsonl",
        [_record("assistant", [{"type": "text", "text": "partial work"}])],
    )
    return meta


@pytest.fixture()
def recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    grant_dir = tmp_path / "grants"
    state_dir = tmp_path / "states"
    monkeypatch.setenv("CLAUDE_RESTART_GRANT_DIR", str(grant_dir))
    monkeypatch.setenv("CLAUDE_RESTART_STATE_DIR", str(state_dir))
    sid = str(uuid.uuid4())
    transcript = tmp_path / "projects" / sid / ".." / f"{sid}.jsonl"
    transcript = transcript.resolve()

    missing_tool = "toolu_missing"
    quota_tool = "toolu_quota"
    complete_tool = "toolu_complete"
    blocked_tool = "toolu_blocked"
    background_tool = "toolu_background"
    background_complete_tool = "toolu_background_complete"
    records = [
        _record("assistant", [_tool_use(missing_tool, "missing parent result")]),
        _record("assistant", [_tool_use(quota_tool, "quota stopped")]),
        _record("user", [_tool_result(
            quota_tool,
            "You've hit your session limit · resets 2:40pm (UTC)\n"
            "agentId: agent-quota (use SendMessage to continue this agent)",
        )]),
        _record("assistant", [_tool_use(complete_tool, "already complete")]),
        _record("user", [_tool_result(
            complete_tool,
            "work completed\nagentId: agent-complete (use SendMessage to continue this agent)",
        )]),
        _record("assistant", [_tool_use(blocked_tool, "hook rejected")]),
        _record("user", [_tool_result(blocked_tool, "PreToolUse Agent hook blocked", error=True)]),
        _record("assistant", [_tool_use(background_tool, "background interrupted", background=True)]),
        _record("user", [_tool_result(
            background_tool,
            "Async agent launched successfully.\nagentId: agent-background",
        )]),
        _record("assistant", [_tool_use(
            background_complete_tool, "background already complete", background=True,
        )]),
        _record("user", [_tool_result(
            background_complete_tool,
            "Async agent launched successfully.\nagentId: agent-background-complete",
        )]),
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": "<task-notification><task-id>agent-background-complete</task-id>"
                "<status>completed</status></task-notification>",
            },
        },
    ]
    _write_jsonl(transcript, records)
    _write_meta(transcript, "agent-missing", missing_tool, "missing parent result")
    _write_meta(transcript, "agent-quota", quota_tool, "quota stopped")
    _write_meta(transcript, "agent-complete", complete_tool, "already complete")
    _write_meta(transcript, "agent-background", background_tool, "background interrupted")
    _write_meta(
        transcript, "agent-background-complete", background_complete_tool,
        "background already complete",
    )
    restart.mint_grant(sid, str(transcript), ttl_seconds=600)
    return {
        "sid": sid,
        "transcript": transcript,
        "grant_dir": grant_dir,
        "state_dir": state_dir,
        "env": {
            **os.environ,
            "CLAUDE_RESTART_GRANT_DIR": str(grant_dir),
            "CLAUDE_RESTART_STATE_DIR": str(state_dir),
            "CLAUDE_CODE_SESSION_ID": sid,
        },
    }


def test_discovery_requires_authoritative_interruption_evidence(recovery: dict) -> None:
    candidates = restart.discover_candidates(recovery["transcript"])
    assert [item["agent_id"] for item in candidates] == [
        "agent-missing", "agent-quota",
    ]
    assert candidates[0]["evidence"] == ["missing_parent_tool_result"]
    assert candidates[1]["evidence"] == ["quota_or_usage_limit"]
    assert "agent-background" not in {item["agent_id"] for item in candidates}
    assert all("prompt" not in item for item in candidates), "raw prompts must not leak into restart state"


def test_discovery_scans_full_parent_and_classifies_notifications(tmp_path: Path) -> None:
    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    old_tool = "toolu_old_quota"
    resumed_tool = "toolu_resumed_quota"
    quota_background_tool = "toolu_background_quota"
    records = [
        _record("assistant", [_tool_use(old_tool, "historical quota")]),
        _record("user", [_tool_result(
            old_tool,
            "You've hit your session limit · resets at 10am (UTC)\nagentId: agent-old",
        )]),
        {"type": "user", "message": {"role": "user", "content": "current request"}},
        _record("assistant", [_tool_use(resumed_tool, "resumed and completed", background=True)]),
        _record("user", [_tool_result(
            resumed_tool,
            "You've hit your session limit · resets at 11am (UTC)\nagentId: agent-resumed",
        )]),
        {
            "type": "queue-operation",
            "content": "<task-notification><task-id>agent-resumed</task-id>"
            "<status>completed</status><result>verified complete</result></task-notification>",
        },
        _record("assistant", [_tool_use(
            quota_background_tool, "background quota", background=True,
        )]),
        _record("user", [_tool_result(
            quota_background_tool,
            "Async agent launched successfully.\nagentId: agent-background-quota",
        )]),
        {
            "type": "queue-operation",
            "content": "<task-notification><task-id>agent-background-quota</task-id>"
            "<status>completed</status><result>You've hit your session limit · "
            "resets in 2h</result></task-notification>",
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": "This session was resumed after the quota reset; recover the same work.",
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": "<command-message>restart</command-message>"
                "<command-name>/restart</command-name>",
            },
        },
        {
            "type": "user",
            "message": {"role": "user", "content": "/restart"},
        },
    ]
    _write_jsonl(transcript, records)
    _write_meta(transcript, "agent-old", old_tool, "historical quota")
    _write_meta(transcript, "agent-resumed", resumed_tool, "resumed and completed")
    _write_meta(
        transcript, "agent-background-quota", quota_background_tool, "background quota",
    )

    candidates = restart.discover_candidates(transcript)
    assert [item["agent_id"] for item in candidates] == [
        "agent-old", "agent-background-quota",
    ]
    assert all(item["evidence"] == ["quota_or_usage_limit"] for item in candidates)


QUOTA_SUMMARY = (
    "Agent \"BA lane\" failed: Agent terminated early due to an API error: "
    "You've hit your session limit · resets 7:50pm (UTC) "
    "(error type rate_limit, HTTP 429, request id req_011Cf, model sent to the "
    "API: claude-opus-5)"
)


def _notification(agent_id: str, status: str, *, summary: str = "", result: str = "") -> str:
    """One notification in the harness element order: status precedes summary."""
    return (
        "<task-notification>"
        f"<task-id>{agent_id}</task-id>"
        f"<tool-use-id>toolu_notify_{agent_id}</tool-use-id>"
        f"<status>{status}</status>"
        f"<summary>{summary}</summary>"
        "<note>A task-notification fires each time this agent stops.</note>"
        f"<result>{result}</result>"
        "</task-notification>"
    )


def test_failed_quota_notification_rearms_a_dispatched_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second session-limit kill must make an already-dispatched resume retryable.

    A subagent revived by SendMessage and killed again by the session limit is
    reported as status=failed with the quota banner in <summary>, and the hard
    kill fires no SubagentStop. The notification is therefore the only evidence
    that can advance interruption_line past interruption_line_at_dispatch, which
    is what prepare_state needs to re-derive dispatched back to pending.
    """
    monkeypatch.setenv("CLAUDE_RESTART_GRANT_DIR", str(tmp_path / "grants"))
    monkeypatch.setenv("CLAUDE_RESTART_STATE_DIR", str(tmp_path / "states"))
    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    tool_id = "toolu_wedged"
    _write_jsonl(transcript, [
        _record("assistant", [_tool_use(tool_id, "twice interrupted lane")]),
        _record("user", [_tool_result(
            tool_id,
            "You've hit your session limit · resets at 4pm (UTC)\nagentId: agent-wedged",
        )]),
    ])
    _write_meta(transcript, "agent-wedged", tool_id, "twice interrupted lane")
    restart.mint_grant(sid, str(transcript), ttl_seconds=600)

    first = restart.prepare_state(sid)
    dispatch_line = first["candidates"][0]["interruption_line"]
    restart.mark_dispatched(sid, "agent-wedged")
    assert restart.authorize_send_message({
        "session_id": sid,
        "tool_input": {
            "to": "agent-wedged",
            "message": first["candidates"][0]["resume_message"],
        },
    })[0] is False, "an in-flight resume must not be dispatched twice"

    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "type": "queue-operation",
            "content": _notification(
                "agent-wedged", "failed",
                summary=QUOTA_SUMMARY,
                result="Now the out-of-scope observation rows.",
            ),
        }) + "\n")

    retried = restart.prepare_state(sid)
    item = next(c for c in retried["candidates"] if c["agent_id"] == "agent-wedged")
    assert item["status"] == "pending"
    assert item["interruption_line"] > dispatch_line
    assert item["evidence"] == ["quota_or_usage_limit"]
    ok, reason = restart.authorize_send_message({
        "session_id": sid,
        "tool_input": {"to": "agent-wedged", "message": item["resume_message"]},
    })
    assert (ok, reason) == (True, "validated /restart recovery")


STOPPED_SUMMARY = (
    "Background agent \"Resuming agent a8ab56b\" didn't finish before the "
    "previous session ended"
)


def test_stopped_notification_rearms_a_dispatched_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host-process teardown must make an already-dispatched resume retryable.

    A subagent revived by SendMessage whose host Claude process then exits
    (account rotation, teardown) is reported as status=stopped with no quota
    text anywhere, and the hard teardown fires no SubagentStop. The stopped
    notification is therefore the only evidence that can advance
    interruption_line past interruption_line_at_dispatch; while it went
    unparsed, the candidate wedged at dispatched and the authorization hook
    refused the redispatch forever (2026-09-28, agent a8ab56bdd1870882d).
    """
    monkeypatch.setenv("CLAUDE_RESTART_GRANT_DIR", str(tmp_path / "grants"))
    monkeypatch.setenv("CLAUDE_RESTART_STATE_DIR", str(tmp_path / "states"))
    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    tool_id = "toolu_torn"
    _write_jsonl(transcript, [
        _record("assistant", [_tool_use(tool_id, "teardown-stopped lane")]),
        _record("user", [_tool_result(
            tool_id,
            "You've hit your session limit · resets at 4pm (UTC)\nagentId: agent-torn",
        )]),
    ])
    _write_meta(transcript, "agent-torn", tool_id, "teardown-stopped lane")
    restart.mint_grant(sid, str(transcript), ttl_seconds=600)

    first = restart.prepare_state(sid)
    dispatch_line = first["candidates"][0]["interruption_line"]
    restart.mark_dispatched(sid, "agent-torn")
    assert restart.authorize_send_message({
        "session_id": sid,
        "tool_input": {
            "to": "agent-torn",
            "message": first["candidates"][0]["resume_message"],
        },
    })[0] is False, "an in-flight resume must not be dispatched twice"

    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "type": "queue-operation",
            "content": _notification("agent-torn", "stopped", summary=STOPPED_SUMMARY),
        }) + "\n")

    retried = restart.prepare_state(sid)
    item = next(c for c in retried["candidates"] if c["agent_id"] == "agent-torn")
    assert item["status"] == "pending"
    assert item["interruption_line"] > dispatch_line
    assert "session_teardown_stop" in item["evidence"]
    ok, reason = restart.authorize_send_message({
        "session_id": sid,
        "tool_input": {"to": "agent-torn", "message": item["resume_message"]},
    })
    assert (ok, reason) == (True, "validated /restart recovery")


def test_notification_status_semantics_are_block_scoped(tmp_path: Path) -> None:
    """Only a clean status=completed block settles a candidate, and never across blocks.

    ``failed`` never means "came to rest", with or without quota text. And when
    one JSONL line carries several notifications, each status belongs to the
    task-id inside its own block: a line-wide DOTALL scan used to pair a failed
    block's task-id with the NEXT block's <status>completed</status>, inverting
    both verdicts at once.
    """
    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    tools = {
        "agent-failed-quota": "toolu_fq",
        "agent-failed-plain": "toolu_fp",
        "agent-stopped-plain": "toolu_sp",
        "agent-completed-clean": "toolu_cc",
    }
    records = [
        _record("assistant", [_tool_use(tools[name], name)])
        for name in tools
    ]
    # One line, three blocks, in an order that lets a bridging match steal the
    # trailing completed status for the two preceding failed blocks.
    records.append({
        "type": "queue-operation",
        "content": (
            _notification("agent-failed-quota", "failed", summary=QUOTA_SUMMARY)
            + _notification(
                "agent-failed-plain", "failed",
                summary="Agent \"lane\" failed: tool use was rejected by a hook",
            )
            + _notification("agent-stopped-plain", "stopped", summary=STOPPED_SUMMARY)
            + _notification(
                "agent-completed-clean", "completed",
                summary="Agent \"lane\" finished", result="all acceptance criteria met",
            )
        ),
    })
    _write_jsonl(transcript, records)
    for name, tool_id in tools.items():
        _write_meta(transcript, name, tool_id, name)

    candidates = {item["agent_id"]: item for item in restart.discover_candidates(transcript)}
    assert "agent-completed-clean" not in candidates, "a clean completion is settled"
    assert candidates["agent-failed-quota"]["evidence"] == [
        "missing_parent_tool_result", "quota_or_usage_limit",
    ]
    # No quota text: the failure adds no evidence of its own, but it must not let
    # the neighbouring completed block mark this candidate as settled either.
    assert candidates["agent-failed-plain"]["evidence"] == ["missing_parent_tool_result"]
    # stopped IS evidence of its own (host process died mid-run), quota or not,
    # and must not be settled by the neighbouring completed block either.
    assert candidates["agent-stopped-plain"]["evidence"] == [
        "missing_parent_tool_result", "session_teardown_stop",
    ]


def test_prepare_authorizes_exact_original_ids_and_message(recovery: dict) -> None:
    view = restart.prepare_state(recovery["sid"])
    assert view["candidate_count"] == 2
    assert view["complete"] is False
    first = view["candidates"][0]
    payload = {
        "tool_name": "SendMessage",
        "session_id": recovery["sid"],
        "tool_input": {"to": first["agent_id"], "message": first["resume_message"]},
    }
    assert restart.authorize_send_message(payload) == (True, "validated /restart recovery")
    # The stored instruction is required as an EXACT PREFIX, not as the whole
    # body: trailing content is how the operator's own guidance rides along, so
    # it is accepted, while altering the instruction itself still is not.
    payload["tool_input"]["message"] += "\nand finish the second half first"
    assert restart.authorize_send_message(payload) == (True, "validated /restart recovery")
    payload["tool_input"]["message"] = first["resume_message"].replace(
        "Resume this exact existing subagent", "Resume this subagent", 1,
    )
    ok, reason = restart.authorize_send_message(payload)
    assert ok is False and "exact restart-v1" in reason
    payload["tool_input"]["message"] = first["resume_message"][:-40]
    ok, reason = restart.authorize_send_message(payload)
    assert ok is False and "exact restart-v1" in reason
    payload["tool_input"] = {
        "to": "agent-not-in-parent",
        "message": restart.build_resume_message(recovery["sid"], "agent-not-in-parent"),
    }
    ok, reason = restart.authorize_send_message(payload)
    assert ok is False and "recoverable interrupted" in reason
    restart.mark_dispatched(recovery["sid"], first["agent_id"])
    payload["tool_input"] = {"to": first["agent_id"], "message": first["resume_message"]}
    ok, reason = restart.authorize_send_message(payload)
    assert ok is False and "duplicate restart dispatch denied" in reason


def test_dispatch_stop_quota_retry_and_finalize(recovery: dict) -> None:
    restart.prepare_state(recovery["sid"])
    restart.mark_dispatched(recovery["sid"], "agent-missing")
    restart.mark_dispatched(recovery["sid"], "agent-quota")
    prepared_again = restart.prepare_state(recovery["sid"])
    quota = next(
        item for item in prepared_again["candidates"] if item["agent_id"] == "agent-quota"
    )
    assert quota["status"] == "dispatched", "an active resume must not be queued twice"
    with recovery["transcript"].open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "type": "queue-operation",
            "content": "<task-notification><task-id>agent-quota</task-id>"
            "<status>completed</status><result>You've hit your session limit · "
            "resets in 1h</result></task-notification>",
        }) + "\n")
    retry_after_new_quota = restart.prepare_state(recovery["sid"])
    quota = next(
        item for item in retry_after_new_quota["candidates"]
        if item["agent_id"] == "agent-quota"
    )
    assert quota["status"] == "pending", "new quota evidence must make a send retryable"
    restart.mark_dispatched(recovery["sid"], "agent-quota")
    view = restart.observe_subagent_stop({
        "session_id": recovery["sid"],
        "agent_id": "agent-missing",
        "stop_hook_active": False,
        "last_assistant_message": "done\nRECOVERY_STATUS: completed",
        "agent_transcript_path": "agent-missing.jsonl",
    })
    assert view is not None and view["complete"] is False
    view = restart.observe_subagent_stop({
        "session_id": recovery["sid"],
        "agent_id": "agent-quota",
        "stop_hook_active": False,
        "last_assistant_message": "You've hit your session limit; resets in 2h",
    })
    assert view is not None and view["complete"] is False
    quota = next(item for item in view["candidates"] if item["agent_id"] == "agent-quota")
    assert quota["status"] == "quota_interrupted"
    with pytest.raises(restart.RestartError, match="remain incomplete"):
        restart.finalize(recovery["sid"])

    retried = restart.prepare_state(recovery["sid"])
    missing = next(item for item in retried["candidates"] if item["agent_id"] == "agent-missing")
    quota = next(item for item in retried["candidates"] if item["agent_id"] == "agent-quota")
    assert missing["status"] == "response_observed"
    assert quota["status"] == "pending"
    restart.mark_dispatched(recovery["sid"], "agent-quota")
    final = restart.observe_subagent_stop({
        "session_id": recovery["sid"],
        "agent_id": "agent-quota",
        "last_assistant_message": "RECOVERY_STATUS: completed",
    })
    assert final is not None and final["complete"] is True
    restart.finalize(recovery["sid"])
    assert not restart.grant_path(recovery["sid"]).exists()


def _run_hook(path: Path, payload: dict, env: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(path)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        cwd=str(ROOT),
        check=False,
    )


def test_background_and_orchestrator_gates_allow_all_runtime_eligible_resumes(recovery: dict) -> None:
    view = restart.prepare_state(recovery["sid"])
    background = HOOKS / "pretool-block-background-tasks.py"
    orchestrator = HOOKS / "pretool-orchestrator-gate.py"
    for candidate in view["candidates"]:
        payload = {
            "tool_name": "SendMessage",
            "session_id": recovery["sid"],
            "tool_input": {
                "to": candidate["agent_id"],
                "message": candidate["resume_message"],
            },
        }
        assert _run_hook(background, payload, recovery["env"]).returncode == 0
        # The ordinary gate permits every runtime-eligible child, not only the first.
        assert _run_hook(orchestrator, payload, recovery["env"]).returncode == 0
    bad = {
        "tool_name": "SendMessage",
        "session_id": recovery["sid"],
        "tool_input": {"to": "agent-missing", "message": "continue"},
    }
    denied = _run_hook(background, bad, recovery["env"])
    assert denied.returncode == 2
    assert "exact restart-v1" in denied.stderr
    ordinary_background = _run_hook(background, {
        "tool_name": "Agent",
        "session_id": recovery["sid"],
        "tool_input": {"subagent_type": "dev", "run_in_background": True},
    }, recovery["env"])
    assert ordinary_background.returncode == 2
    foreground = _run_hook(background, {
        "tool_name": "Agent",
        "session_id": recovery["sid"],
        "tool_input": {"subagent_type": "dev", "run_in_background": False},
    }, recovery["env"])
    assert foreground.returncode == 0
    try:
        Path(f"/tmp/claude-tool-streak-{recovery['sid']}.json").unlink()
    except FileNotFoundError:
        pass


def test_posttool_and_subagentstop_hooks_update_journal(recovery: dict) -> None:
    view = restart.prepare_state(recovery["sid"])
    candidate = view["candidates"][0]
    payload = {
        "tool_name": "SendMessage",
        "session_id": recovery["sid"],
        "tool_input": {"to": candidate["agent_id"], "message": candidate["resume_message"]},
        "tool_response": {"status": "sent"},
    }
    sent = _run_hook(HOOKS / "posttool-restart-sendmessage.py", payload, recovery["env"])
    assert sent.returncode == 0
    status = restart.get_status(recovery["sid"])
    updated = next(item for item in status["candidates"] if item["agent_id"] == candidate["agent_id"])
    assert updated["status"] == "dispatched" and updated["attempts"] == 1

    stopped = _run_hook(HOOKS / "subagentstop-restart-track.py", {
        "session_id": recovery["sid"],
        "agent_id": candidate["agent_id"],
        "last_assistant_message": "RECOVERY_STATUS: completed",
        "stop_hook_active": False,
    }, recovery["env"])
    assert stopped.returncode == 0
    status = restart.get_status(recovery["sid"])
    updated = next(item for item in status["candidates"] if item["agent_id"] == candidate["agent_id"])
    assert updated["status"] == "response_observed"


def test_userprompt_authorizer_accepts_only_human_command_invocations(tmp_path: Path) -> None:
    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    _write_jsonl(transcript, [])
    env = {
        **os.environ,
        "CLAUDE_RESTART_GRANT_DIR": str(tmp_path / "grants"),
        "CLAUDE_RESTART_STATE_DIR": str(tmp_path / "states"),
    }
    hook = HOOKS / "userprompt-restart-authorize.py"
    base = {"session_id": sid, "transcript_path": str(transcript), "cwd": str(tmp_path)}
    for mention in ("please run /restart once quota resets", "/restarts", "/do /restart now"):
        ignored = _run_hook(hook, {**base, "prompt": mention}, env)
        assert ignored.returncode == 0
        assert not (tmp_path / "grants" / f"claude-restart-grant-{sid}.json").exists()
    subagent = _run_hook(hook, {**base, "prompt": "/restart carry this", "agent_id": "agent-child"}, env)
    assert subagent.returncode == 0
    assert not (tmp_path / "grants" / f"claude-restart-grant-{sid}.json").exists()
    accepted = _run_hook(hook, {**base, "prompt": "/restart"}, env)
    assert accepted.returncode == 0
    assert "capability issued for parent session" in accepted.stdout
    assert "authenticated" not in accepted.stdout
    grant = json.loads((tmp_path / "grants" / f"claude-restart-grant-{sid}.json").read_text())
    assert grant["issued_by"] == restart.GRANT_ISSUER
    assert grant["session_id"] == sid
    assert not (tmp_path / "grants" / f"claude-restart-args-{sid}.txt").exists()


def test_userprompt_authorizer_carries_operator_argument_verbatim(tmp_path: Path) -> None:
    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    _write_jsonl(transcript, [])
    env = {
        **os.environ,
        "CLAUDE_RESTART_GRANT_DIR": str(tmp_path / "grants"),
        "CLAUDE_RESTART_STATE_DIR": str(tmp_path / "states"),
    }
    hook = HOOKS / "userprompt-restart-authorize.py"
    base = {"session_id": sid, "transcript_path": str(transcript), "cwd": str(tmp_path)}
    grant_file = tmp_path / "grants" / f"claude-restart-grant-{sid}.json"
    args_file = tmp_path / "grants" / f"claude-restart-args-{sid}.txt"
    guidance = '继续，下一阶段注意 X\n\n{"quote": "it\'s \\"fine\\""}\ttab\r\nend  '
    accepted = _run_hook(hook, {**base, "prompt": f"/restart   {guidance}"}, env)
    assert accepted.returncode == 0
    assert "capability issued for parent session" in accepted.stdout
    assert guidance not in accepted.stdout
    assert json.loads(grant_file.read_text())["issued_by"] == restart.GRANT_ISSUER
    assert args_file.read_bytes() == guidance.encode("utf-8")
    newline_form = _run_hook(hook, {**base, "prompt": f"  /restart\n{guidance}\t"}, env)
    assert newline_form.returncode == 0
    assert args_file.read_bytes() == f"{guidance}\t".encode("utf-8")
    large = '百万言 "quoted" {json}\n' * 4000
    assert len(large.encode("utf-8")) > 100_000
    big = _run_hook(hook, {**base, "prompt": f"/restart {large}"}, env)
    assert big.returncode == 0
    assert args_file.read_bytes() == large.encode("utf-8")
    bare = _run_hook(hook, {**base, "prompt": " /restart  "}, env)
    assert bare.returncode == 0
    assert json.loads(grant_file.read_text())["session_id"] == sid
    assert not args_file.exists()


def test_command_and_settings_keep_restart_human_only_and_lossless() -> None:
    command = (ROOT / "commands" / "restart.md").read_text(encoding="utf-8")
    assert "disable-model-invocation: true" in command
    assert "DO NOT call `Agent` or `Task`" in command
    assert "every recoverable interrupted subagent" in command
    assert "latest affected human request" not in command
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "every recoverable interrupted child in the current parent transcript" in readme
    assert "latest quota-interrupted request" not in readme
    test_source = Path(__file__).read_text(encoding="utf-8")
    assert re.search(r"authenticated(?:_| )+(?:child|resum)", test_source, re.IGNORECASE) is None
    hooks_index = (HOOKS / "INDEX.md").read_text(encoding="utf-8")
    hooks_readme = (HOOKS / "README.md").read_text(encoding="utf-8")
    for name in ("posttool-restart-sendmessage.py",
                 "subagentstop-restart-track.py", "userprompt-restart-authorize.py"):
        assert (HOOKS / name).is_file()
        assert f"`{name}`" in hooks_index and f"`{name}`" in hooks_readme
    lib_index = (HOOKS / "lib" / "INDEX.md").read_text(encoding="utf-8")
    lib_readme = (HOOKS / "lib" / "README.md").read_text(encoding="utf-8")
    assert (HOOKS / "lib" / "subagent_restart.py").is_file()
    assert "`subagent_restart.py`" in lib_index and "`subagent_restart.py`" in lib_readme
    assert "SID=" not in command
    assert "$HOME/.claude/venv/bin/python" in command
    assert "## Why this preserves content" not in command
    settings = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))
    template = json.loads((ROOT / "settings.template.json").read_text(encoding="utf-8"))
    for config in (settings, template):
        assert config["env"]["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] == "1"
        assert "Skill(restart:*)" in config["permissions"]["deny"]
        pretool_commands = json.dumps(config["hooks"]["PreToolUse"])
        posttool_commands = json.dumps(config["hooks"]["PostToolUse"])
        assert "posttool-restart-sendmessage.py" not in pretool_commands
        assert "posttool-restart-sendmessage.py" in posttool_commands


def test_restart_helper_bash_command_bypasses_workflow_gate_deadlock(tmp_path: Path) -> None:
    """/restart's own helper must run even when the invoking session holds an
    unrelated, never-acknowledged bookmark (e.g. /dev was invoked and
    interrupted before its first TodoWrite) — without the gate being disabled
    for anything else."""
    gate = HOOKS / "pretool-workflow-gate.py"
    project_dir = tmp_path / "project"
    (project_dir / ".claude").mkdir(parents=True)
    sid = str(uuid.uuid4())
    bookmark = project_dir / ".claude" / f"workflow-{sid}.json"
    bookmark.write_text(json.dumps({
        "command": "dev", "arguments": "", "todo_acknowledged": False,
    }))
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    home = Path(os.environ.get("HOME", str(Path.home())))

    restart_call = {
        "tool_name": "Bash",
        "session_id": sid,
        "tool_input": {
            "command": f"{home}/.claude/venv/bin/python "
            f"{home}/.claude/scripts/restart-subagents.py prepare",
        },
    }
    allowed = _run_hook(gate, restart_call, env)
    assert allowed.returncode == 0, allowed.stderr

    cross_account_call = {
        "tool_name": "Bash",
        "session_id": sid,
        "tool_input": {
            "command": f"{home}/.claude/venv/bin/python "
            f"{home}/.claude/scripts/restart-subagents.py prepare --cross-account",
        },
    }
    cross_allowed = _run_hook(gate, cross_account_call, env)
    assert cross_allowed.returncode == 0, (
        "the documented --cross-account prepare variant must share the deadlock "
        f"exemption: {cross_allowed.stderr}"
    )

    ordinary_call = {
        "tool_name": "Bash",
        "session_id": sid,
        "tool_input": {"command": "echo hello"},
    }
    blocked = _run_hook(gate, ordinary_call, env)
    assert blocked.returncode == 2
    assert "CHECKLIST NOT STARTED" in blocked.stderr

    chained_call = {
        "tool_name": "Bash",
        "session_id": sid,
        "tool_input": {
            "command": f"{home}/.claude/venv/bin/python "
            f"{home}/.claude/scripts/restart-subagents.py prepare"
            " && rm -rf /tmp/should-not-run",
        },
    }
    chained_blocked = _run_hook(gate, chained_call, env)
    assert chained_blocked.returncode == 2, "chained command must not bypass the gate"


def test_restart_helper_bypass_fails_closed_on_unsafe_home(tmp_path: Path) -> None:
    """If $HOME itself contains whitespace/shell-special characters, the literal
    $HOME text in the command cannot be trusted to expand to a single clean
    word — the bypass must fail closed rather than assume the expansion is
    safe."""
    gate = HOOKS / "pretool-workflow-gate.py"
    project_dir = tmp_path / "project"
    (project_dir / ".claude").mkdir(parents=True)
    sid = str(uuid.uuid4())
    bookmark = project_dir / ".claude" / f"workflow-{sid}.json"
    bookmark.write_text(json.dumps({
        "command": "dev", "arguments": "", "todo_acknowledged": False,
    }))
    unsafe_home = tmp_path / "evil home; rm -rf"
    unsafe_home.mkdir(parents=True)
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir), "HOME": str(unsafe_home)}

    restart_call = {
        "tool_name": "Bash",
        "session_id": sid,
        "tool_input": {
            "command": "$HOME/.claude/venv/bin/python $HOME/.claude/scripts/restart-subagents.py prepare",
        },
    }
    blocked = _run_hook(gate, restart_call, env)
    assert blocked.returncode == 2, "unsafe $HOME must not be trusted to grant the bypass"
    assert "CHECKLIST NOT STARTED" in blocked.stderr


def test_prepare_defaults_to_own_session_and_gates_cross_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default discovery is scoped to the invoking session's own transcript: a
    genuinely interrupted subagent left by ANOTHER account's same-project
    session must stay out of the candidate set unless the human explicitly
    opted into cross-account discovery at prepare time, and only a state
    carrying that recorded opt-in may authorize a foreign-origin dispatch."""
    monkeypatch.setenv("CLAUDE_RESTART_GRANT_DIR", str(tmp_path / "grants"))
    monkeypatch.setenv("CLAUDE_RESTART_STATE_DIR", str(tmp_path / "states"))
    accounts_root = tmp_path / "accounts"
    monkeypatch.setattr(restart, "ACCOUNTS_ROOT", accounts_root)

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    slug = restart.project_slug(project_dir)

    operator_sid = str(uuid.uuid4())
    operator_transcript = accounts_root / "yugetang" / "claude" / "projects" / slug / f"{operator_sid}.jsonl"
    op_tool = "toolu_operator_missing"
    _write_jsonl(operator_transcript, [_record("assistant", [_tool_use(op_tool, "operator interrupted")])])
    _write_meta(operator_transcript, "agent-operator", op_tool, "operator interrupted")

    foreign_sid = str(uuid.uuid4())
    foreign_transcript = accounts_root / "orchestrade" / "claude" / "projects" / slug / f"{foreign_sid}.jsonl"
    fx_tool = "toolu_foreign_missing"
    _write_jsonl(foreign_transcript, [_record("assistant", [_tool_use(fx_tool, "foreign interrupted")])])
    _write_meta(foreign_transcript, "agent-foreign", fx_tool, "foreign interrupted")

    # Account roots hold byte-copies of the same session file (observed in the
    # 20260915 corpus: "7 agents appear twice, once per account root"). A copy
    # shares the operator's session id, so foreign-ness must be decided by
    # origin transcript path, never by session id alone.
    copy_transcript = accounts_root / "orchestrade" / "claude" / "projects" / slug / f"{operator_sid}.jsonl"
    copy_tool = "toolu_copy_missing"
    _write_jsonl(copy_transcript, [_record("assistant", [_tool_use(copy_tool, "copied interrupted")])])
    _write_meta(copy_transcript, "copycat-foreign", copy_tool, "copied interrupted")

    restart.mint_grant(operator_sid, str(operator_transcript), ttl_seconds=600)

    default_view = restart.prepare_state(operator_sid, project_dir=project_dir)
    assert default_view["cross_account"] is False
    assert {item["agent_id"] for item in default_view["candidates"]} == {"agent-operator"}

    cross_view = restart.prepare_state(operator_sid, project_dir=project_dir, cross_account=True)
    assert cross_view["cross_account"] is True
    origins = {item["agent_id"]: item["parent_session_id"] for item in cross_view["candidates"]}
    assert origins == {
        "agent-operator": operator_sid,
        "agent-foreign": foreign_sid,
        "copycat-foreign": operator_sid,
    }
    foreign_item = next(item for item in cross_view["candidates"] if item["agent_id"] == "agent-foreign")
    assert f"parent_session_id={foreign_sid}" in foreign_item["resume_message"]
    assert foreign_item["origin_transcript_path"] == str(foreign_transcript)
    copycat_item = next(item for item in cross_view["candidates"] if item["agent_id"] == "copycat-foreign")
    assert copycat_item["origin_transcript_path"] == str(copy_transcript)
    payload = {
        "tool_name": "SendMessage",
        "session_id": operator_sid,
        "tool_input": {"to": "agent-foreign", "message": foreign_item["resume_message"]},
    }
    copycat_payload = {
        "tool_name": "SendMessage",
        "session_id": operator_sid,
        "tool_input": {"to": "copycat-foreign", "message": copycat_item["resume_message"]},
    }
    assert restart.authorize_send_message(payload) == (True, "validated /restart recovery")
    assert restart.authorize_send_message(copycat_payload) == (True, "validated /restart recovery")

    # The opt-in is epoch-bound: after a LATER bare /restart mints a fresh
    # grant, the stale cross-account state must stop authorizing foreign sends
    # until the operator explicitly re-opts in under the new grant.
    restart.mint_grant(operator_sid, str(operator_transcript), ttl_seconds=600)
    ok, reason = restart.authorize_send_message(payload)
    assert ok is False and "stale" in reason
    recross_view = restart.prepare_state(operator_sid, project_dir=project_dir, cross_account=True)
    foreign_item = next(item for item in recross_view["candidates"] if item["agent_id"] == "agent-foreign")
    payload["tool_input"]["message"] = foreign_item["resume_message"]
    assert restart.authorize_send_message(payload) == (True, "validated /restart recovery")

    # A state without the recorded opt-in — e.g. any legacy state file predating
    # the flag, whose stale foreign entries may still sit on disk — must fail
    # closed on foreign-origin targets, INCLUDING the same-session-id copy.
    state_file = Path(recross_view["state_path"])
    state = json.loads(state_file.read_text(encoding="utf-8"))
    state.pop("cross_account", None)
    state_file.write_text(json.dumps(state), encoding="utf-8")
    ok, reason = restart.authorize_send_message(payload)
    assert ok is False and "another parent session" in reason
    ok, reason = restart.authorize_send_message(copycat_payload)
    assert ok is False and "another parent session" in reason

    # Re-running prepare without the flag drops foreign candidates entirely.
    reverted = restart.prepare_state(operator_sid, project_dir=project_dir)
    assert {item["agent_id"] for item in reverted["candidates"]} == {"agent-operator"}


def test_authorize_refuses_candidate_without_recorded_origin_transcript(
    recovery: dict,
) -> None:
    """Locality must be PROVEN, never assumed. A candidate carrying no recorded
    origin transcript — the shape of every state file written before the field
    existed — cannot be shown to be local, because account roots hold diverging
    transcripts that share a session-id stem. Such a candidate must be refused
    even when its parent_session_id equals the operator's own session id, and
    the refusal must name the remedy (re-run prepare, which records the origin
    for every genuine candidate)."""
    view = restart.prepare_state(recovery["sid"])
    candidate = next(i for i in view["candidates"] if i["agent_id"] == "agent-missing")
    assert candidate["parent_session_id"] == recovery["sid"]
    assert candidate["origin_transcript_path"] == str(recovery["transcript"])
    payload = {
        "tool_name": "SendMessage",
        "session_id": recovery["sid"],
        "tool_input": {"to": candidate["agent_id"], "message": candidate["resume_message"]},
    }
    # Origin recorded and equal to the grant-bound transcript: normal path.
    assert restart.authorize_send_message(payload) == (True, "validated /restart recovery")

    state_file = Path(view["state_path"])
    state = json.loads(state_file.read_text(encoding="utf-8"))
    for item in state["candidates"]:
        item.pop("origin_transcript_path", None)
    state_file.write_text(json.dumps(state), encoding="utf-8")
    assert state["candidates"][0]["parent_session_id"] == recovery["sid"]

    ok, reason = restart.authorize_send_message(payload)
    assert ok is False, "unprovable locality must fail closed, not degrade to session id"
    assert "origin" in reason and "prepare" in reason


def test_authorize_rechecks_child_completion_at_dispatch_time(recovery: dict) -> None:
    """A child that delivers its terminal end_turn report between prepare and
    dispatch (or a legacy-state candidate never structurally screened) must be
    refused at authorization time — completed agents are never resumed."""
    view = restart.prepare_state(recovery["sid"])
    candidate = next(i for i in view["candidates"] if i["agent_id"] == "agent-missing")
    payload = {
        "tool_name": "SendMessage",
        "session_id": recovery["sid"],
        "tool_input": {"to": candidate["agent_id"], "message": candidate["resume_message"]},
    }
    assert restart.authorize_send_message(payload) == (True, "validated /restart recovery")
    _write_jsonl(Path(candidate["agent_transcript_path"]), [
        {"type": "assistant", "message": {
            "role": "assistant", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "terminal report"}],
        }},
    ])
    ok, reason = restart.authorize_send_message(payload)
    assert ok is False and "end_turn" in reason


def test_discovery_excludes_children_with_terminal_end_turn_reports(tmp_path: Path) -> None:
    """A child whose own transcript reached stop_reason=end_turn finished
    naturally and must never be resumed — even when its clean report quotes
    quota banners (the 39/217 false-positive corpus of
    docs/reference/restart-detector-quota-text-match-false-positive-20260915.md)
    and even when a later re-woken turn was itself cut off afterwards."""
    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    reporter_tool = "toolu_reporter"
    rewoken_tool = "toolu_rewoken"
    genuine_tool = "toolu_genuine"
    records = [
        _record("assistant", [_tool_use(reporter_tool, "quota recon report")]),
        _record("user", [_tool_result(
            reporter_tool,
            "The other session's last entry is verbatim: You've hit your session"
            " limit · resets 9:20pm (UTC)\nagentId: reporter-clean",
        )]),
        _record("assistant", [_tool_use(rewoken_tool, "reported then rewoken")]),
        _record("assistant", [_tool_use(genuine_tool, "genuinely cut off")]),
    ]
    _write_jsonl(transcript, records)
    _write_meta(transcript, "reporter-clean", reporter_tool, "quota recon report")
    _write_meta(transcript, "rewoken-cut", rewoken_tool, "reported then rewoken")
    _write_meta(transcript, "genuine-cut", genuine_tool, "genuinely cut off")
    subagents = transcript.with_suffix("") / "subagents"
    _write_jsonl(subagents / "agent-reporter-clean.jsonl", [
        {"type": "assistant", "message": {
            "role": "assistant", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "clean report quoting: resets 9:20pm"}],
        }},
    ])
    _write_jsonl(subagents / "agent-rewoken-cut.jsonl", [
        {"type": "assistant", "message": {
            "role": "assistant", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "terminal report"}],
        }},
        {"type": "assistant", "isApiErrorMessage": True, "message": {
            "role": "assistant", "stop_reason": "stop_sequence",
            "content": [{"type": "text",
                         "text": "You've hit your session limit · resets 3:50pm (UTC)"}],
        }},
    ])
    # agent-genuine keeps the fixture's report-less child transcript.

    candidates = restart.discover_candidates(transcript)
    assert {item["agent_id"] for item in candidates} == {"genuine-cut"}


def test_discovery_resolves_end_turn_across_split_account_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each account login persists its own PARTIAL copy of one logical session,
    so a child's terminal end_turn record can be missing from the copy reachable
    via the parent's own directory while living in another account's copy
    (measured 2026-10-01 on session 4758df81: three finished children were
    listed as resumable from the parent-side copy alone). Completion evidence is
    positive and monotone, so the strongest verdict across copies must win — for
    a plain finisher and for one whose clean report merely quotes a quota banner
    — while a child with no end_turn record in ANY copy is still recovered."""
    accounts_root = tmp_path / "accounts"
    monkeypatch.setattr(restart, "ACCOUNTS_ROOT", accounts_root)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    slug = restart.project_slug(project_dir)

    sid = str(uuid.uuid4())
    transcript = accounts_root / "yugoge" / "claude" / "projects" / slug / f"{sid}.jsonl"
    other_subagents = (
        accounts_root / "orchestrade" / "claude" / "projects" / slug / sid / "subagents"
    )
    split_tool, quota_tool, cut_tool = "toolu_split", "toolu_quota_split", "toolu_cut"
    _write_jsonl(transcript, [
        _record("assistant", [_tool_use(split_tool, "finished, report split off")]),
        _record("assistant", [_tool_use(quota_tool, "reported on a quota outage")]),
        _record("user", [_tool_result(
            quota_tool,
            "You've hit your session limit · resets 9:20pm (UTC)\nagentId: quota-reporter",
        )]),
        _record("assistant", [_tool_use(cut_tool, "genuinely cut off")]),
    ])
    for agent_id, tool_id, description in (
        ("split-finisher", split_tool, "finished, report split off"),
        ("quota-reporter", quota_tool, "reported on a quota outage"),
        ("never-finished", cut_tool, "genuinely cut off"),
    ):
        _write_meta(transcript, agent_id, tool_id, description)

    # The non-parent root is the ONLY place these two children's terminal
    # end_turn records survive: _write_meta left the parent-side copies holding
    # nothing but the report-less "partial work" record.
    for agent_id, text in (
        ("split-finisher", "terminal report"),
        ("quota-reporter", "clean report quoting: resets 9:20pm"),
    ):
        _write_jsonl(other_subagents / f"agent-{agent_id}.jsonl", [
            {"type": "assistant", "message": {
                "role": "assistant", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": text}],
            }},
        ])

    parent_copy = transcript.with_suffix("") / "subagents" / "agent-split-finisher.jsonl"
    assert restart._scan_child_transcript(parent_copy)["end_turn"] is False
    assert other_subagents / "agent-split-finisher.jsonl" in restart._child_transcript_copies(
        parent_copy
    )
    assert restart._child_transcript_signals(parent_copy)["end_turn"] is True

    candidates = restart.discover_candidates(transcript)
    assert {item["agent_id"] for item in candidates} == {"never-finished"}


def test_discovery_keeps_candidate_when_child_transcript_is_unreadable(tmp_path: Path) -> None:
    """Liveness is only provable from the child transcript; when that file is
    missing, parent-side interruption evidence must keep the candidate — the
    detector fails toward recovering a genuinely cut-off child, never toward
    silently dropping it."""
    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    tool = "toolu_lost_child"
    _write_jsonl(transcript, [_record("assistant", [_tool_use(tool, "lost child transcript")])])
    meta_path = _write_meta(transcript, "lost-child", tool, "lost child transcript")
    (meta_path.parent / "agent-lost-child.jsonl").unlink()

    candidates = restart.discover_candidates(transcript)
    assert [item["agent_id"] for item in candidates] == ["lost-child"]
    assert candidates[0]["evidence"] == ["missing_parent_tool_result"]


def test_observe_stop_prefers_recovery_status_sentinel_over_quota_text(recovery: dict) -> None:
    """A resumed agent reporting ON a quota outage legitimately quotes limit
    banners; the explicit RECOVERY_STATUS sentinel demanded by the fixed resume
    message must outrank the quota text-match when grading its response."""
    restart.prepare_state(recovery["sid"])
    restart.mark_dispatched(recovery["sid"], "agent-missing")
    view = restart.observe_subagent_stop({
        "session_id": recovery["sid"],
        "agent_id": "agent-missing",
        "last_assistant_message": "the outage banner read: You've hit your session"
        " limit · resets 2:40pm (UTC)\nRECOVERY_STATUS: completed",
    })
    assert view is not None
    item = next(i for i in view["candidates"] if i["agent_id"] == "agent-missing")
    assert item["status"] == "response_observed"

    restart.mark_dispatched(recovery["sid"], "agent-quota")
    view = restart.observe_subagent_stop({
        "session_id": recovery["sid"],
        "agent_id": "agent-quota",
        "last_assistant_message": "partial work only\nRECOVERY_STATUS: quota_interrupted",
    })
    assert view is not None
    item = next(i for i in view["candidates"] if i["agent_id"] == "agent-quota")
    assert item["status"] == "quota_interrupted"


def test_cli_resolves_session_id_from_claude_environment(recovery: dict) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "restart-subagents.py"), "prepare"],
        text=True,
        capture_output=True,
        env=recovery["env"],
        cwd=str(ROOT),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    view = json.loads(result.stdout)
    assert view["parent_session_id"] == recovery["sid"]
    assert view["cross_account"] is False


def test_cli_prepare_cross_account_requires_explicit_flag(
    recovery: dict, tmp_path: Path,
) -> None:
    """The CLI records the human's --cross-account opt-in in the prepared state;
    the env pins the accounts root and project dir to empty temp paths so the
    subprocess sweep can never touch real account transcripts."""
    env = {
        **recovery["env"],
        "CLAUDE_RESTART_ACCOUNTS_ROOT": str(tmp_path / "empty-accounts"),
        "CLAUDE_PROJECT_DIR": str(tmp_path / "project"),
    }
    (tmp_path / "empty-accounts").mkdir()
    (tmp_path / "project").mkdir()
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "restart-subagents.py"),
         "prepare", "--cross-account"],
        text=True,
        capture_output=True,
        env=env,
        cwd=str(ROOT),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    view = json.loads(result.stdout)
    assert view["cross_account"] is True
    assert view["parent_session_id"] == recovery["sid"]


# The resume instruction as it stood BEFORE operator guidance existed, pinned
# byte-for-byte: 675 bytes, sha256 6028cdbd2f…c78e, measured from the
# pre-guidance implementation. A bare /restart must keep producing exactly this,
# so any future drift fails here instead of silently changing what every
# recovered agent is told.
BASELINE_RESUME_MESSAGE = (
    "[awesome-claude-harness/restart-v1]\n"
    "parent_session_id=sess-baseline-0001\n"
    "agent_id=agent-baseline-0001\n"
    "\n"
    "Resume this exact existing subagent from its persisted transcript after a quota or session-limit interruption.\n"
    "First inspect the last tool call/result and current workspace side effects. Do not replay irreversible operations.\n"
    "Continue only the original single assigned issue; do not broaden scope and do not spawn a replacement agent.\n"
    "If the original work was already complete, make no duplicate edits and re-emit the terminal report after verification.\n"
    "If quota blocks again, end with `RECOVERY_STATUS: quota_interrupted`; otherwise end with `RECOVERY_STATUS: completed`."
)
BASELINE_RESUME_SHA256 = "6028cdbd2fae7645feff64d18695f447157ec115fdfb76fccef1c7348f24c78e"

# Exotic bytes and a payload over 100 KB: guidance carries whatever the operator
# typed, at whatever length, so both must survive producer -> consumer untouched.
GUIDANCE_SAMPLES = {
    "exotic": '继续，先查 A；then "quoted" & \'quoted\'\n\n\ttab kept\r\nend  ',
    "large": '百万言 "quoted" {json} \t\n' * 5000,
}


def test_bare_restart_resume_message_is_byte_identical_to_the_pinned_baseline() -> None:
    """With no guidance the resume message is byte-for-byte what it always was."""
    message = restart.build_resume_message("sess-baseline-0001", "agent-baseline-0001")
    raw = message.encode("utf-8")
    assert message == BASELINE_RESUME_MESSAGE
    assert hashlib.sha256(raw).hexdigest() == BASELINE_RESUME_SHA256
    assert len(raw) == 675
    # None and "" are the two ways "no guidance" reaches the builder; neither may
    # emit an empty marker block.
    for absent in (None, ""):
        assert restart.build_resume_message(
            "sess-baseline-0001", "agent-baseline-0001", absent,
        ) == BASELINE_RESUME_MESSAGE
    assert restart.GUIDANCE_OPEN not in message
    # And the instruction stays an EXACT prefix once guidance is present.
    guided = restart.build_resume_message(
        "sess-baseline-0001", "agent-baseline-0001", "do X first",
    )
    assert guided.startswith(BASELINE_RESUME_MESSAGE)
    assert guided.encode("utf-8").startswith(raw)
    assert guided[len(BASELINE_RESUME_MESSAGE):].endswith(restart.GUIDANCE_CLOSE)


def test_operator_guidance_reaches_the_resumed_agent_verbatim_and_prefix_is_enforced(
    recovery: dict,
) -> None:
    """Producer -> consumer end to end: the /restart authorizer persists the
    operator's words, prepare carries them after the fixed instruction, and the
    SendMessage authorizer accepts that message while still refusing any message
    whose instruction prefix was altered."""
    hook = HOOKS / "userprompt-restart-authorize.py"
    base_payload = {
        "session_id": recovery["sid"],
        "transcript_path": str(recovery["transcript"]),
        "cwd": str(recovery["transcript"].parent),
    }
    assert len(GUIDANCE_SAMPLES["large"].encode("utf-8")) > 100_000

    for label, guidance in GUIDANCE_SAMPLES.items():
        issued = _run_hook(hook, {**base_payload, "prompt": f"/restart {guidance}"}, recovery["env"])
        assert issued.returncode == 0, issued.stderr
        # Sanity: the producer stored the operator's bytes unchanged.
        assert restart.guidance_path(recovery["sid"]).read_bytes() == guidance.encode("utf-8")

        view = restart.prepare_state(recovery["sid"])
        assert view["operator_guidance"] == guidance, label
        assert view["candidate_count"] == 2, label
        for item in view["candidates"]:
            fixed = restart.build_resume_message(
                item["parent_session_id"], item["agent_id"],
            )
            message = item["resume_message"]
            assert message.startswith(fixed), label
            assert message.encode("utf-8").startswith(fixed.encode("utf-8")), label
            tail = message[len(fixed):]
            # Verbatim: the operator's bytes appear once, as one contiguous run,
            # with nothing truncated, escaped, re-wrapped or normalised.
            assert message.encode("utf-8").count(guidance.encode("utf-8")) == 1, label
            assert restart.GUIDANCE_OPEN in tail and tail.endswith(restart.GUIDANCE_CLOSE), label

        candidate = next(item for item in view["candidates"] if item["status"] == "pending")
        stored = candidate["resume_message"]
        fixed = restart.build_resume_message(
            candidate["parent_session_id"], candidate["agent_id"],
        )

        def _auth(message: str) -> tuple[bool, str]:
            return restart.authorize_send_message({
                "session_id": recovery["sid"],
                "tool_input": {"to": candidate["agent_id"], "message": message},
            })

        assert _auth(stored)[0] is True, label
        assert _auth(stored + "\n\nPS: one more operator note")[0] is True, label

        lines = fixed.split("\n")
        reordered = "\n".join(lines[:4] + [lines[5], lines[4]] + lines[6:]) + stored[len(fixed):]
        reworded = stored.replace(
            "Resume this exact existing subagent", "Resume this subagent", 1,
        )
        assert reworded != stored and reordered != stored
        for tampered, why in (
            (reworded, "reworded instruction"),
            (stored[: len(fixed) - 25] + stored[len(fixed):], "truncated instruction"),
            (reordered, "reordered instruction"),
            (fixed, "operator guidance dropped"),
            ("read this first\n" + stored, "instruction is no longer the prefix"),
            (None, "non-string body"),
        ):
            allowed, reason = _auth(tampered)
            assert allowed is False, f"{label}: {why} must be refused"
            assert "restart-v1 recovery message" in reason, f"{label}: {why}"


def test_operator_guidance_is_per_session_and_never_replayed_once_cleared(
    recovery: dict, tmp_path: Path,
) -> None:
    """Guidance belongs to one session's one invocation: it must not appear in
    another session's prepared state, and a later bare /restart (which removes
    the file) must not keep delivering the earlier invocation's words."""
    guidance = "only session A asked for this"
    restart.guidance_path(recovery["sid"]).write_bytes(guidance.encode("utf-8"))
    mine = restart.prepare_state(recovery["sid"])
    assert mine["operator_guidance"] == guidance

    other_sid = str(uuid.uuid4())
    other_transcript = tmp_path / f"{other_sid}.jsonl"
    _write_jsonl(other_transcript, [])
    restart.mint_grant(other_sid, str(other_transcript), ttl_seconds=600)
    theirs = restart.prepare_state(other_sid)
    assert theirs["operator_guidance"] is None
    assert guidance not in json.dumps(theirs, ensure_ascii=False)
    assert guidance not in restart.state_path(other_sid).read_text(encoding="utf-8")

    restart.guidance_path(recovery["sid"]).unlink()
    after = restart.prepare_state(recovery["sid"])
    assert after["operator_guidance"] is None
    assert guidance not in json.dumps(after, ensure_ascii=False)
    assert guidance not in restart.state_path(recovery["sid"]).read_text(encoding="utf-8")
    for item in after["candidates"]:
        assert item["resume_message"] == restart.build_resume_message(
            item["parent_session_id"], item["agent_id"],
        )


def test_cli_prepare_exposes_operator_guidance_even_with_zero_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The prepared output carries the guidance as its own top-level field, so a
    caller can read it when discovery found NO candidate to hang it off."""
    monkeypatch.setenv("CLAUDE_RESTART_GRANT_DIR", str(tmp_path / "grants"))
    monkeypatch.setenv("CLAUDE_RESTART_STATE_DIR", str(tmp_path / "states"))
    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    _write_jsonl(transcript, [])  # no Agent calls at all -> zero candidates
    restart.mint_grant(sid, str(transcript), ttl_seconds=600)
    guidance = '继续: 收尾前先跑 restart 套件\n\t"tab kept"'
    restart.guidance_path(sid).write_bytes(guidance.encode("utf-8"))
    env = {**os.environ, "CLAUDE_CODE_SESSION_ID": sid}

    for command in ("prepare", "status"):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "restart-subagents.py"), command],
            text=True, capture_output=True, env=env, cwd=str(ROOT), check=False,
        )
        assert result.returncode == 0, result.stderr
        view = json.loads(result.stdout)
        assert view["candidate_count"] == 0 and view["candidates"] == []
        assert "operator_guidance" in view, command
        assert view["operator_guidance"] == guidance, command


def test_load_guidance_tolerates_absent_unreadable_and_undecodable_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guidance is additive, so every way of failing to read it degrades to None:
    losing the operator's words must never cost the recovery itself."""
    monkeypatch.setenv("CLAUDE_RESTART_GRANT_DIR", str(tmp_path / "grants"))
    sid = str(uuid.uuid4())
    assert restart.load_guidance(sid) is None, "absent"
    path = restart.guidance_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    assert restart.load_guidance(sid) is None, "empty"
    path.write_bytes(b"\xff\xfe not utf-8 at all")
    assert restart.load_guidance(sid) is None, "undecodable"
    path.unlink()
    path.mkdir()
    assert restart.load_guidance(sid) is None, "unreadable"
    path.rmdir()
    assert restart.load_guidance("bad/session/id") is None, "invalid session id"
    path.write_bytes("a\r\n\tb".encode("utf-8"))
    assert restart.load_guidance(sid) == "a\r\n\tb", "CRLF and tabs must survive the read"

    # One path convention, bound to its producer at runtime rather than restated.
    assert path.parent == restart.grant_path(sid).parent
    assert path.name == f"claude-restart-args-{sid}.txt"
    spec = importlib.util.spec_from_file_location(
        "restart_authorize_producer", HOOKS / "userprompt-restart-authorize.py",
    )
    producer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(producer)
    assert producer.guidance_path(sid) == restart.guidance_path(sid), (
        "the consumer must read exactly the path the /restart authorizer writes"
    )


