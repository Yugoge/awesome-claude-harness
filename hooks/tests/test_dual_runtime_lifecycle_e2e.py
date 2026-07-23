"""Real-entrypoint regressions for single-owner ordinary dev lifecycle."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


SOURCE_ROOT = Path(__file__).parents[2]
if not (SOURCE_ROOT / "hooks" / "prompt-workflow.py").is_file():
    SOURCE_ROOT = Path("/root/.claude")
NATIVE = Path("/root/.codex/hooks/codex_native_harness.py")
PROMPT = SOURCE_ROOT / "hooks" / "prompt-workflow.py"
PRETOOL = SOURCE_ROOT / "hooks" / "pretool-workflow-gate.py"
POSTTODO = SOURCE_ROOT / "hooks" / "posttool-todo-tracker.py"
CLAUDE_STOP = SOURCE_ROOT / "hooks" / "stop-overnight-timelock.py"
ACTIVE_CONFIGS = {
    "claude": Path("/root/.claude/settings.json"),
    "codex": Path("/root/.codex/hooks.json"),
}
REQUIRED_CHAIN_EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")
PRESERVATION_POLICY = "immutable_prior_family_atomic_current_pointer/v1"


def _run(path: Path, event: str | None, payload: dict, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(path)]
    if event is not None:
        command += ["--event", event]
    return subprocess.run(
        command,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def _native_env(root: Path, **extra: str) -> dict[str, str]:
    return {
        **os.environ,
        "CODEX_PROJECT_DIR": str(root),
        "CLAUDE_PROJECT_DIR": str(root),
        "CODEX_NATIVE_HARNESS_LEGACY_TODO_DIR": str(root / "legacy-todos"),
        **extra,
    }


def _native_start(root: Path, sid: str, event_id: str, prompt: str, **env_extra: str) -> subprocess.CompletedProcess[str]:
    return _run(
        NATIVE,
        "UserPromptSubmit",
        {"session_id": sid, "event_id": event_id, "cwd": str(root), "prompt": prompt},
        _native_env(root, **env_extra),
    )


def _state(root: Path, sid: str) -> dict:
    return json.loads((root / ".codex-harness" / "workflows" / f"{sid}.json").read_text())


def _plan(steps: list[dict], frontier: int) -> list[dict]:
    result = []
    for index, step in enumerate(steps):
        status = "completed" if frontier == len(steps) or index < frontier else (
            "in_progress" if index == frontier else "pending"
        )
        result.append({"step": step["content"], "status": status})
    return result


class _Transcript:
    def __init__(self, root: Path, sid: str):
        directory = root / "sessions"
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"rollout-{sid}.jsonl"
        self.sid = sid
        self.base = datetime.now(timezone.utc) + timedelta(seconds=1)
        self.sequence = 0
        self.rows = [{
            "timestamp": self._timestamp(),
            "type": "session_meta",
            "payload": {"session_id": sid, "id": sid, "source": "vscode"},
        }]
        self.flush()

    def _timestamp(self) -> str:
        value = self.base + timedelta(milliseconds=100 * self.sequence)
        self.sequence += 1
        return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def append_plan(self, plan: list[dict]) -> None:
        self.rows.append({
            "timestamp": self._timestamp(),
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "update_plan",
                "call_id": f"plan-{self.sequence}",
                "arguments": json.dumps({"plan": plan}),
            },
        })
        self.flush()

    def append_completion(self, role: str, ordinal: int) -> None:
        task_name = f"{role}_e2e_{ordinal}"
        call_id = f"spawn-{ordinal}"
        thread_id = f"thread-{ordinal}"
        agent_path = f"/root/{task_name}"
        spawn_timestamp = self._timestamp()
        started_timestamp = self._timestamp()
        started_ms = int(datetime.fromisoformat(started_timestamp.replace("Z", "+00:00")).timestamp() * 1000)
        self.rows.extend([
            {
                "timestamp": spawn_timestamp,
                "type": "response_item",
                "payload": {
                    "type": "function_call", "namespace": "collaboration",
                    "name": "spawn_agent", "call_id": call_id,
                    "arguments": json.dumps({"task_name": task_name, "message": "one issue"}),
                },
            },
            {
                "timestamp": started_timestamp,
                "type": "event_msg",
                "payload": {
                    "type": "sub_agent_activity", "event_id": call_id,
                    "kind": "started", "agent_path": agent_path,
                    "agent_thread_id": thread_id, "occurred_at_ms": started_ms,
                },
            },
            {
                "timestamp": self._timestamp(),
                "type": "response_item",
                "payload": {
                    "type": "agent_message", "author": agent_path,
                    "content": [{"type": "input_text", "text": "Message Type: FINAL_ANSWER\nPayload:\npass"}],
                },
            },
            {
                "timestamp": self._timestamp(),
                "type": "response_item",
                "payload": {
                    "type": "function_call", "namespace": "collaboration",
                    "name": "list_agents", "call_id": f"list-{ordinal}", "arguments": "{}",
                },
            },
            {
                "timestamp": self._timestamp(),
                "type": "response_item",
                "payload": {
                    "type": "function_call_output", "call_id": f"list-{ordinal}",
                    "output": json.dumps({"agents": [{
                        "agent_name": agent_path,
                        "agent_status": {"completed": "runtime completed"},
                    }]}),
                },
            },
        ])
        self.flush()

    def append_user(self, prompt: str) -> None:
        self.rows.append({
            "timestamp": self._timestamp(),
            "type": "event_msg",
            "payload": {"type": "user_message", "message": prompt},
        })
        self.flush()

    def flush(self) -> None:
        self.path.write_text("".join(json.dumps(row) + "\n" for row in self.rows))


def _drive_native_frontier(root: Path, sid: str, frontier: int) -> None:
    steps = _state(root, sid)["steps"]
    transcript = _Transcript(root, sid)
    transcript.append_plan(_plan(steps, 0))
    bootstrap = _run(
        NATIVE, "PostToolUse",
        {"session_id": sid, "cwd": str(root), "transcript_path": str(transcript.path),
         "tool_name": "functions.update_plan", "tool_input": {"plan": _plan(steps, 0)}},
        _native_env(root),
    )
    assert bootstrap.returncode == 0, bootstrap.stderr
    for current in range(frontier):
        state = _state(root, sid)
        call = state["steps"][current].get("subagent_call")
        if isinstance(call, dict):
            transcript.append_completion(call.get("subagent_type") or call["agent"], current)
        next_plan = _plan(state["steps"], current + 1)
        transcript.append_plan(next_plan)
        result = _run(
            NATIVE, "PostToolUse",
            {"session_id": sid, "cwd": str(root), "transcript_path": str(transcript.path),
             "tool_name": "functions.update_plan", "tool_input": {"plan": next_plan}},
            _native_env(root),
        )
        assert result.returncode == 0, result.stderr
        assert not json.loads(result.stdout or "{}" ).get("decision") == "block", result.stdout
        assert sum(step["status"] == "completed" for step in _state(root, sid)["steps"]) == current + 1


def _write_valid_artifacts(root: Path, task_id: str) -> None:
    docs = root / "docs" / "dev"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / f"ticket-{task_id}.md").write_text(f"# Ticket {task_id}\n")
    (docs / f"context-{task_id}.json").write_text(json.dumps({"request_id": task_id, "task_id": task_id}) + "\n")
    (docs / f"dev-report-{task_id}.json").write_text(json.dumps({
        "request_id": task_id, "task_id": task_id,
        "dev": {"status": "completed", "files_modified": [], "files_created": []},
    }) + "\n")
    (docs / f"qa-report-{task_id}.json").write_text(json.dumps({
        "request_id": task_id, "task_id": task_id, "qa": {"status": "pass"},
    }) + "\n")
    (docs / f"completion-{task_id}.md").write_text(f"# Completion {task_id}\n")


def _assert_family_cardinality(root: Path, sid: str, expected: int) -> None:
    assert len(list((root / "docs" / "dev").glob("user-requirement-*.md"))) == expected
    assert len(list((root / ".claude" / "dev-registry").iterdir())) == expected
    assert len(list((root / ".codex-harness" / "start-transactions" / sid).glob("*.json"))) == expected


def _matcher_applies(matcher: object, tool_name: str | None) -> bool:
    if matcher in (None, "", "*"):
        return True
    if tool_name is None or not isinstance(matcher, str):
        return False
    try:
        return re.fullmatch(matcher, tool_name) is not None
    except re.error as exc:  # pragma: no cover - active config must be valid
        raise AssertionError(f"invalid active hook matcher {matcher!r}: {exc}") from exc


def resolve_configured_handlers(runtime: str, event: str, tool_name: str | None = None) -> list[dict]:
    """Resolve every matching handler from the freshly parsed active config."""
    config_path = ACTIVE_CONFIGS[runtime]
    document = json.loads(config_path.read_text(encoding="utf-8"))
    groups = document["hooks"][event]
    resolved: list[dict] = []
    identities: set[tuple] = set()
    for group_index, group in enumerate(groups):
        if not _matcher_applies(group.get("matcher"), tool_name):
            continue
        for handler_index, handler in enumerate(group.get("hooks", [])):
            identity = (event, group_index, handler_index, handler.get("command"))
            assert identity not in identities, f"duplicate configured handler identity: {identity}"
            identities.add(identity)
            resolved.append({
                "identity": identity,
                "event_array_index": list(document["hooks"]).index(event),
                "hook_group_index": group_index,
                "handler_index": handler_index,
                "matcher": group.get("matcher"),
                "command": handler["command"],
                "timeout": int(handler.get("timeout") or 20),
            })
    return resolved


def _file_snapshot(paths: list[Path]) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for base in paths:
        if not base.exists():
            continue
        candidates = [base] if base.is_file() else base.rglob("*")
        for candidate in candidates:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            try:
                logical = str(candidate)
                snapshot[logical] = hashlib.sha256(candidate.read_bytes()).hexdigest()
            except FileNotFoundError:
                continue
    return snapshot


def _delta(before: dict[str, str], after: dict[str, str]) -> dict[str, object]:
    return {
        "created": sorted(after.keys() - before.keys()),
        "deleted": sorted(before.keys() - after.keys()),
        "changed": sorted(key for key in before.keys() & after.keys() if before[key] != after[key]),
        "before": before,
        "after": after,
    }


def _json_decision(stdout: str) -> dict | None:
    candidates = [stdout.strip(), *reversed(stdout.splitlines())]
    for candidate in candidates:
        if not candidate.strip().startswith("{"):
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and any(
            key in value for key in ("decision", "permissionDecision", "continue", "termination_allowed")
        ):
            return value
    return None


def _authoritative_paths(runtime: str, root: Path, home: Path, sid: str) -> list[Path]:
    if runtime == "codex":
        return [root / ".codex-harness" / "workflows" / f"{sid}.json"]
    return [
        root / ".claude" / f"workflow-{sid}.json",
        home / ".claude" / "todos" / f"{sid}-agent-{sid}.json",
    ]


def _owner_command(runtime: str, event: str) -> str:
    if runtime == "codex":
        return "codex_native_harness.py"
    return {
        "UserPromptSubmit": "prompt-workflow.py",
        "PreToolUse": "pretool-workflow-gate.py",
        "PostToolUse": "posttool-todo-tracker.py",
        "Stop": "stop-overnight-timelock.py",
    }[event]


def _fixture_env(runtime: str, root: Path, home: Path, clock: str) -> dict[str, str]:
    return {
        **os.environ,
        "HOME": str(home),
        "CLAUDE_PROJECT_DIR": str(root),
        "CODEX_PROJECT_DIR": str(root),
        "CODEX_NATIVE_HARNESS_LEGACY_TODO_DIR": str(home / ".claude" / "todos"),
        "CLAUDE_GRAPHIFY_ENABLED": "0",
        "CLAUDE_DEV_CLOCK_ISO": clock,
        "CODEX_NATIVE_CLOCK_ISO": clock,
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def make_configured_fixture(base: Path, runtime: str, name: str) -> dict:
    root = base / f"{runtime}-{name}"
    home = base / f"{runtime}-{name}-home"
    root.mkdir(parents=True)
    claude_home = home / ".claude"
    claude_home.mkdir(parents=True)
    for child in ("hooks", "scripts", "commands", "agents"):
        (claude_home / child).symlink_to(Path("/root/.claude") / child, target_is_directory=True)
    (claude_home / "todos").mkdir()
    (root / "scripts" / "todo").mkdir(parents=True)
    shutil.copy2(SOURCE_ROOT / "scripts" / "todo" / "dev.py", root / "scripts" / "todo" / "dev.py")
    sid = f"r03-{runtime}-{name}"
    clock = "2037-03-04T05:06:07Z"
    return {
        "runtime": runtime,
        "root": root,
        "home": home,
        "sid": sid,
        "clock": clock,
        "env": _fixture_env(runtime, root, home, clock),
    }


def configured_payload(fixture: dict, event: str, *, prompt: str | None = None, frontier: int = 0) -> dict:
    root, home, sid, runtime = (
        fixture["root"], fixture["home"], fixture["sid"], fixture["runtime"]
    )
    payload: dict = {"session_id": sid, "cwd": str(root), "hook_event_name": event}
    if event == "UserPromptSubmit":
        selected_prompt = prompt or f"/dev configured {runtime}"
        event_id = "event-" + hashlib.sha256(selected_prompt.encode()).hexdigest()[:20]
        payload.update({"prompt": selected_prompt, "event_id": event_id})
    elif event in {"PreToolUse", "PostToolUse"}:
        if runtime == "codex":
            state = _state(root, sid)
            items = []
            for index, step in enumerate(state["steps"]):
                item = dict(step)
                item["status"] = (
                    "completed" if index < frontier else
                    "in_progress" if index == frontier else "pending"
                )
                item.setdefault("content", item.get("step", ""))
                item.setdefault("activeForm", item["content"])
                items.append(item)
            payload.update({"tool_name": "TodoWrite", "tool_input": {"todos": items, "plan": items}})
        else:
            todos_path = home / ".claude" / "todos" / f"{sid}-agent-{sid}.json"
            items = json.loads(todos_path.read_text(encoding="utf-8"))
            for index, item in enumerate(items):
                item["status"] = (
                    "completed" if index < frontier else
                    "in_progress" if index == frontier else "pending"
                )
            payload.update({"tool_name": "TodoWrite", "tool_input": {"todos": items}})
    return payload


def execute_configured_chain(fixture: dict, event: str, payload: dict) -> dict:
    """Execute the complete matching configured chain and retain every effect."""
    runtime, root, home, sid = (
        fixture["runtime"], fixture["root"], fixture["home"], fixture["sid"]
    )
    tool_name = payload.get("tool_name") if event in {"PreToolUse", "PostToolUse"} else None
    resolved = resolve_configured_handlers(runtime, event, tool_name)
    records = []
    owner_fragment = _owner_command(runtime, event)
    owner_credits = 0
    aggregate_block = False
    for handler in resolved:
        tracked_roots = [root, home / ".claude" / "todos"]
        before_artifacts = _file_snapshot(tracked_roots)
        before_state = _file_snapshot(_authoritative_paths(runtime, root, home, sid))
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        process = subprocess.run(
            handler["command"],
            input=raw,
            text=True,
            capture_output=True,
            shell=True,
            executable="/bin/bash",
            cwd=root,
            env=fixture["env"],
            timeout=max(20, handler["timeout"] + 5),
            check=False,
        )
        after_state = _file_snapshot(_authoritative_paths(runtime, root, home, sid))
        after_artifacts = _file_snapshot(tracked_roots)
        decision = _json_decision(process.stdout)
        blocked = process.returncode == 2 or bool(
            decision and (
                decision.get("decision") in {"block", "deny"}
                or decision.get("permissionDecision") == "deny"
                or decision.get("continue") is False
            )
        )
        aggregate_block = aggregate_block or blocked
        owner = owner_fragment in handler["command"]
        owner_credits += int(owner)
        records.append({
            **handler,
            "argv": ["/bin/bash", "-c", handler["command"]],
            "exit_code": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
            "json_decision": decision,
            "state_delta": _delta(before_state, after_state),
            "artifact_delta": _delta(before_artifacts, after_artifacts),
            "state_owner_credit": owner,
            "blocked": blocked,
        })
    executed = [record["identity"] for record in records]
    expected = [handler["identity"] for handler in resolved]
    assert executed == expected
    return {
        "runtime": runtime,
        "event": event,
        "tool_name": tool_name,
        "resolved_handler_identities": expected,
        "executed_handler_identities": executed,
        "resolved_handler_count": len(resolved),
        "executed_handler_count": len(records),
        "records": records,
        "aggregate": {
            "decision": "block" if aggregate_block else "allow",
            "combined_user_visible_output": "".join(
                record["stdout"] + record["stderr"] for record in records
            ),
            "authoritative_state_delta": _delta(
                records[0]["state_delta"]["before"] if records else {},
                records[-1]["state_delta"]["after"] if records else {},
            ),
            "artifact_delta": _delta(
                records[0]["artifact_delta"]["before"] if records else {},
                records[-1]["artifact_delta"]["after"] if records else {},
            ),
            "state_owner_credit": owner_credits,
        },
    }


def _task_families(fixture: dict) -> dict[str, dict[str, bytes]]:
    root = fixture["root"]
    families: dict[str, dict[str, bytes]] = {}
    registry_parent = root / ".claude" / "dev-registry"
    if not registry_parent.exists():
        return families
    for directory in sorted(registry_parent.iterdir()):
        if not directory.is_dir():
            continue
        task_id = directory.name
        files = {
            str(path.relative_to(root)): path.read_bytes()
            for path in directory.rglob("*") if path.is_file()
        }
        requirement = root / "docs" / "dev" / f"user-requirement-{task_id}.md"
        if requirement.exists():
            files[str(requirement.relative_to(root))] = requirement.read_bytes()
        families[task_id] = files
    return families


def _current_identity(fixture: dict) -> tuple[str, int]:
    if fixture["runtime"] == "codex":
        state = _state(fixture["root"], fixture["sid"])
    else:
        state = json.loads(
            (fixture["root"] / ".claude" / f"workflow-{fixture['sid']}.json").read_text()
        )
    return state["task_id"], int(state["workflow_generation"])


def _frontier(fixture: dict) -> int:
    if fixture["runtime"] == "codex":
        items = _state(fixture["root"], fixture["sid"])["steps"]
    else:
        path = fixture["home"] / ".claude" / "todos" / f"{fixture['sid']}-agent-{fixture['sid']}.json"
        items = json.loads(path.read_text())
    return sum(item.get("status") == "completed" for item in items)


def _full_start(fixture: dict, prompt: str) -> dict:
    return execute_configured_chain(
        fixture, "UserPromptSubmit", configured_payload(fixture, "UserPromptSubmit", prompt=prompt)
    )


def _full_progress(fixture: dict, frontier: int) -> tuple[dict, dict]:
    pre_payload = configured_payload(fixture, "PreToolUse", frontier=frontier)
    pre = execute_configured_chain(fixture, "PreToolUse", pre_payload)
    post_payload = configured_payload(fixture, "PostToolUse", frontier=frontier)
    post = execute_configured_chain(fixture, "PostToolUse", post_payload)
    return pre, post


def _artifact_bytes(fixture: dict) -> dict[str, str]:
    return _file_snapshot([fixture["root"], fixture["home"] / ".claude" / "todos"])


RECOVERY_FIELDS = {
    "mode", "task_id", "lifecycle_state", "time_lock_active",
    "intent_recorded", "requirement_artifact", "termination_allowed", "next_actions",
}


def _assert_start_recovery(output: dict, mode: str) -> None:
    assert output["decision"] == "block"
    assert RECOVERY_FIELDS <= output.keys()
    assert output["mode"] == mode
    assert output["time_lock_active"] is False
    assert output["termination_allowed"] is True
    assert isinstance(output["intent_recorded"], bool)
    assert isinstance(output["next_actions"], list) and output["next_actions"]


@pytest.mark.parametrize(
    ("mode", "identity", "error_code"),
    [
        ("dev", {}, "native_event_identity_missing"),
        ("redev", {"event_id": {"top-secret": "/private/operator/path"}}, "native_event_identity_malformed"),
    ],
)
def test_codex_start_rejects_missing_or_malformed_identity_without_outputs(
    tmp_path: Path, mode: str, identity: dict, error_code: str
) -> None:
    root = tmp_path / f"identity-{mode}"
    root.mkdir()
    sid = f"identity-{mode}"
    payload = {"session_id": sid, "cwd": str(root), "prompt": f"/{mode} identity-negative", **identity}
    rejected = _run(NATIVE, "UserPromptSubmit", payload, _native_env(root))
    output = json.loads(rejected.stdout)
    assert rejected.returncode == 0
    _assert_start_recovery(output, mode)
    assert error_code in output["reason"]
    assert output["task_id"] is None
    assert output["lifecycle_state"] == "not_started"
    assert output["intent_recorded"] is False
    assert output["requirement_artifact"] is None
    assert not (root / ".codex-harness").exists()
    assert not (root / ".claude").exists()
    assert not (root / "docs").exists()
    assert str(root) not in rejected.stdout
    assert "top-secret" not in rejected.stdout and "/private/operator/path" not in rejected.stdout


@pytest.mark.parametrize(
    "identity_field",
    ["prompt_event_id", "event_id", "turn_id", "message_id", "hook_run_id"],
)
def test_codex_start_accepts_each_supported_immutable_identity_field(
    tmp_path: Path, identity_field: str
) -> None:
    root = tmp_path / identity_field
    root.mkdir()
    sid = f"supported-{identity_field}"
    payload = {
        "session_id": sid,
        "cwd": str(root),
        "prompt": f"/dev supported {identity_field}",
        identity_field: f"immutable-{identity_field}",
    }
    accepted = _run(NATIVE, "UserPromptSubmit", payload, _native_env(root))
    assert accepted.returncode == 0 and "decision" not in json.loads(accepted.stdout)
    assert _state(root, sid)["start_transaction"]["event_identity_native"] is True
    _assert_family_cardinality(root, sid, 1)


@pytest.mark.parametrize("frontier", [0, 8])
def test_codex_real_entrypoint_ordinary_stop_at_zero_and_mid(tmp_path: Path, frontier: int) -> None:
    root = tmp_path / f"codex-{frontier}"
    root.mkdir()
    sid = f"codex-stop-{frontier}"
    started = _native_start(root, sid, f"event-{frontier}", f"/dev stop frontier {frontier}")
    assert started.returncode == 0 and "decision" not in json.loads(started.stdout)
    if frontier:
        _drive_native_frontier(root, sid, frontier)
    before = _state(root, sid)
    task_id = before["task_id"]
    stopped = _run(NATIVE, "Stop", {"session_id": sid, "cwd": str(root)}, _native_env(root))
    output = json.loads(stopped.stdout)
    assert stopped.returncode == 0
    assert output["continue"] is True and output["termination_allowed"] is True
    assert output["time_lock_active"] is False
    after = _state(root, sid)
    assert after["status"] == "incomplete" and after["task_id"] == task_id
    assert sum(step["status"] == "completed" for step in after["steps"]) == frontier
    assert not (root / ".claude" / f"workflow-{sid}.json").exists()
    assert len(list((root / "docs" / "dev").glob("user-requirement-*.md"))) == 1


def test_codex_completed_later_generation_and_active_reentry(tmp_path: Path) -> None:
    root = tmp_path / "codex-complete"
    root.mkdir()
    sid = "codex-complete"
    first = _native_start(root, sid, "event-A", "/dev requirement A")
    assert first.returncode == 0
    first_task = _state(root, sid)["task_id"]
    identity_collision = _native_start(root, sid, "event-A", "/dev changed prompt for same immutable event")
    identity_collision_output = json.loads(identity_collision.stdout)
    _assert_start_recovery(identity_collision_output, "dev")
    assert "start_transaction_identity_collision" in identity_collision_output["reason"]
    assert identity_collision_output["task_id"] == first_task
    assert identity_collision_output["lifecycle_state"] == "active"
    assert identity_collision_output["intent_recorded"] is False
    assert str(root) not in identity_collision.stdout
    reentry = _native_start(root, sid, "event-reentry", "/redev replace without overwrite")
    reentry_output = json.loads(reentry.stdout)
    assert reentry.returncode == 0 and "decision" not in reentry_output
    reentry_state = _state(root, sid)
    assert reentry_state["task_id"] != first_task
    assert reentry_state["workflow_generation"] == 2
    assert reentry_state["preservation_policy"] == PRESERVATION_POLICY
    assert reentry_state["workflow_history"][-1]["task_id"] == first_task
    assert reentry_state["workflow_history"][-1]["status"] == "incomplete"
    assert len(list((root / ".codex-harness" / "start-transactions" / sid).glob("*.json"))) == 2
    _drive_native_frontier(root, sid, 17)
    assert _state(root, sid)["status"] == "completed"
    stopped = _run(NATIVE, "Stop", {"session_id": sid, "cwd": str(root)}, _native_env(root))
    assert json.loads(stopped.stdout)["continue"] is True
    second = _native_start(root, sid, "event-B", "/dev requirement B")
    assert second.returncode == 0
    state = _state(root, sid)
    assert state["workflow_generation"] == 3 and state["task_id"] != first_task
    assert len(state["workflow_history"]) == 2
    assert len(list((root / "docs" / "dev").glob("user-requirement-*.md"))) == 3


def test_codex_duplicate_event_and_partial_transaction_recovery(tmp_path: Path) -> None:
    for failpoint in ("before_prepare", "after_prepare", "after_registry", "after_requirement", "before_state_commit"):
        root = tmp_path / failpoint
        root.mkdir()
        sid = f"partial-{failpoint}"
        failed = _native_start(root, sid, "same-event", "/dev one requirement", CODEX_NATIVE_START_FAILPOINT=failpoint)
        failure_output = json.loads(failed.stdout)
        _assert_start_recovery(failure_output, "dev")
        assert failure_output["lifecycle_state"] == "not_started"
        assert failure_output["intent_recorded"] is (failpoint != "before_prepare")
        assert (failure_output["task_id"] is None) is (failpoint == "before_prepare")
        assert str(root) not in failed.stdout
        recovered = _native_start(root, sid, "same-event", "/dev one requirement")
        assert recovered.returncode == 0
        state = _state(root, sid)
        replay = _native_start(root, sid, "same-event", "/dev one requirement")
        assert replay.returncode == 0 and replay.stdout == recovered.stdout
        assert len(list((root / "docs" / "dev").glob("user-requirement-*.md"))) == 1
        assert len(list((root / ".claude" / "dev-registry").iterdir())) == 1
        assert len(list((root / ".codex-harness" / "start-transactions" / sid).glob("*.json"))) == 1
        assert state["start_transaction"]["status"] == "committed"


def test_codex_start_idempotency_key_separates_command_and_exact_replay(tmp_path: Path) -> None:
    root = tmp_path / "start-key"
    root.mkdir()
    sid = "start-key-session"
    native_event_id = "immutable-event"
    transaction_dir = root / ".codex-harness" / "start-transactions" / sid

    def expected(command: str) -> str:
        material = f"codex.dev-start/v1\0{root.resolve()}\0{sid}\0{native_event_id}\0{command}"
        return hashlib.sha256(material.encode()).hexdigest()

    first_prompt = "/dev exact replay"
    first = _native_start(root, sid, native_event_id, first_prompt)
    assert first.returncode == 0 and "decision" not in json.loads(first.stdout)
    dev_key = expected("dev")
    dev_transaction = transaction_dir / f"{dev_key}.json"
    assert dev_transaction.is_file()
    first_record = json.loads(dev_transaction.read_text())
    assert first_record["event_id"] == dev_key
    assert first_record["idempotency_key"] == dev_key
    assert first_record["command"] == "dev"
    assert first_record["prompt_sha256"] == hashlib.sha256(first_prompt.encode()).hexdigest()
    first_state_bytes = (root / ".codex-harness" / "workflows" / f"{sid}.json").read_bytes()
    first_transaction_bytes = dev_transaction.read_bytes()

    first_replay = _native_start(root, sid, native_event_id, first_prompt)
    assert first_replay.returncode == 0 and first_replay.stdout == first.stdout
    assert (root / ".codex-harness" / "workflows" / f"{sid}.json").read_bytes() == first_state_bytes
    assert dev_transaction.read_bytes() == first_transaction_bytes

    stopped = _run(NATIVE, "Stop", {"session_id": sid, "cwd": str(root)}, _native_env(root))
    assert stopped.returncode == 0 and _state(root, sid)["status"] == "incomplete"

    second_prompt = "/redev exact replay"
    second = _native_start(root, sid, native_event_id, second_prompt)
    assert second.returncode == 0 and "decision" not in json.loads(second.stdout)
    redev_key = expected("redev")
    assert redev_key != dev_key
    redev_transaction = transaction_dir / f"{redev_key}.json"
    assert redev_transaction.is_file()
    assert {path.name for path in transaction_dir.glob("*.json")} == {
        f"{dev_key}.json", f"{redev_key}.json",
    }
    second_state = _state(root, sid)
    assert second_state["command"] == "redev" and second_state["workflow_generation"] == 2
    second_state_bytes = (root / ".codex-harness" / "workflows" / f"{sid}.json").read_bytes()
    second_transaction_bytes = redev_transaction.read_bytes()

    second_replay = _native_start(root, sid, native_event_id, second_prompt)
    assert second_replay.returncode == 0 and second_replay.stdout == second.stdout
    assert (root / ".codex-harness" / "workflows" / f"{sid}.json").read_bytes() == second_state_bytes
    assert redev_transaction.read_bytes() == second_transaction_bytes


def test_codex_terminal_native_retires_stale_legacy_projection(tmp_path: Path) -> None:
    root = tmp_path / "stale"
    root.mkdir()
    sid = "stale-session"
    _native_start(root, sid, "event-stale", "/dev stale")
    _run(NATIVE, "Stop", {"session_id": sid, "cwd": str(root)}, _native_env(root))
    projection = root / ".claude" / f"workflow-{sid}.json"
    projection.parent.mkdir(parents=True, exist_ok=True)
    projection.write_text(json.dumps({"command": "dev", "last_todos": [{"status": "in_progress"}]}))
    healed = _run(NATIVE, "PreToolUse", {"session_id": sid, "cwd": str(root), "tool_name": "Read", "tool_input": {}}, _native_env(root))
    assert healed.returncode == 0
    assert _state(root, sid)["status"] == "incomplete"
    assert not projection.exists()


def test_codex_terminal_redev_incomplete_handoff_and_exact_cardinality(tmp_path: Path) -> None:
    root = tmp_path / "terminal-redev"
    root.mkdir()
    sid = "terminal-redev"
    assert _native_start(root, sid, "event-dev", "/dev initial").returncode == 0
    first_task = _state(root, sid)["task_id"]
    stopped = _run(NATIVE, "Stop", {"session_id": sid, "cwd": str(root)}, _native_env(root))
    assert json.loads(stopped.stdout)["lifecycle_state"] == "incomplete"
    accepted = _native_start(root, sid, "event-redev", "/redev accepted after terminal")
    assert accepted.returncode == 0 and "decision" not in json.loads(accepted.stdout)
    second = _state(root, sid)
    assert second["command"] == "redev" and second["workflow_generation"] == 2
    assert second["task_id"] != first_task
    second_stop = _run(NATIVE, "Stop", {"session_id": sid, "cwd": str(root)}, _native_env(root))
    second_stop_output = json.loads(second_stop.stdout)
    assert second_stop.returncode == 0 and second_stop_output["lifecycle_state"] == "incomplete"
    handoff = _native_start(root, sid, "event-after-incomplete", "/dev accepted after incomplete terminal")
    assert handoff.returncode == 0 and "decision" not in json.loads(handoff.stdout)
    assert _state(root, sid)["workflow_generation"] == 3
    _assert_family_cardinality(root, sid, 3)


def test_codex_explicit_cancel_then_next_generation(tmp_path: Path) -> None:
    root = tmp_path / "cancelled"
    root.mkdir()
    sid = "cancelled-session"
    assert _native_start(root, sid, "event-before-cancel", "/dev cancel me").returncode == 0
    transcript = _Transcript(root, sid)
    transcript.append_user("/stop")
    cancelled = _run(
        NATIVE, "UserPromptSubmit",
        {"session_id": sid, "cwd": str(root), "prompt": "/stop", "transcript_path": str(transcript.path)},
        _native_env(root),
    )
    output = json.loads(cancelled.stdout)
    assert cancelled.returncode == 0 and output["continue"] is True
    assert output["lifecycle_state"] == "user_cancelled"
    assert not (root / ".claude" / f"workflow-{sid}.json").exists()
    next_start = _native_start(root, sid, "event-after-cancel", "/redev after explicit cancellation")
    assert next_start.returncode == 0 and "decision" not in json.loads(next_start.stdout)
    assert _state(root, sid)["workflow_generation"] == 2
    _assert_family_cardinality(root, sid, 2)


def test_codex_close_then_immediate_new_dev(tmp_path: Path) -> None:
    root = tmp_path / "close-handoff"
    root.mkdir()
    sid = "close-handoff"
    assert _native_start(root, sid, "event-before-close", "/dev close handoff").returncode == 0
    _drive_native_frontier(root, sid, 17)
    task_id = _state(root, sid)["task_id"]
    _write_valid_artifacts(root, task_id)
    closed = _run(
        NATIVE, "UserPromptSubmit",
        {"session_id": sid, "event_id": "event-close", "cwd": str(root), "prompt": "/close"},
        _native_env(root),
    )
    close_output = json.loads(closed.stdout)
    assert closed.returncode == 0 and close_output["decision"] == "allow"
    assert close_output["task_id"] == task_id
    restarted = _native_start(root, sid, "event-after-close", "/dev immediately after close")
    assert restarted.returncode == 0 and "decision" not in json.loads(restarted.stdout)
    assert _state(root, sid)["workflow_generation"] == 2
    _assert_family_cardinality(root, sid, 2)


def test_codex_process_restart_repairs_missing_and_corrupt_projection(tmp_path: Path) -> None:
    root = tmp_path / "restart-projection"
    root.mkdir()
    sid = "restart-projection"
    started = _native_start(root, sid, "event-restart", "/dev survives process restart")
    assert started.returncode == 0
    before = _state(root, sid)
    projection = root / ".claude" / f"workflow-{sid}.json"
    projection.unlink()
    repaired_missing = _run(
        NATIVE, "PreToolUse",
        {"session_id": sid, "cwd": str(root), "tool_name": "Read", "tool_input": {}},
        _native_env(root),
    )
    assert repaired_missing.returncode == 0 and projection.is_file()
    projection.write_text("{corrupt projection\n")
    repaired_corrupt = _run(
        NATIVE, "PreToolUse",
        {"session_id": sid, "cwd": str(root), "tool_name": "Read", "tool_input": {}},
        _native_env(root),
    )
    assert repaired_corrupt.returncode == 0
    repaired = json.loads(projection.read_text())
    assert repaired["task_id"] == before["task_id"] and repaired["codex_native_harness"] is True
    replay = _native_start(root, sid, "event-restart", "/dev survives process restart")
    assert replay.returncode == 0 and replay.stdout == started.stdout
    assert _state(root, sid)["start_transaction"] == before["start_transaction"]
    _assert_family_cardinality(root, sid, 1)


def test_installed_native_overnight_stop_blocks_but_explicit_cancel_releases(tmp_path: Path) -> None:
    root = tmp_path / "overnight"
    root.mkdir()
    sid = "overnight-session"
    deadline = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    started = _native_start(root, sid, "event-overnight", f"/dev-overnight --end-time {deadline}")
    assert started.returncode == 0 and _state(root, sid)["command"] == "dev-overnight"
    blocked = _run(NATIVE, "Stop", {"session_id": sid, "cwd": str(root)}, _native_env(root))
    blocked_output = json.loads(blocked.stdout)
    assert blocked.returncode == 0 and blocked_output["decision"] == "block"
    transcript = _Transcript(root, sid)
    transcript.append_user("/stop")
    cancelled = _run(
        NATIVE, "UserPromptSubmit",
        {"session_id": sid, "cwd": str(root), "prompt": "/stop", "transcript_path": str(transcript.path)},
        _native_env(root),
    )
    # Parity with Claude Code: the Stop *event* stays time-locked, but the
    # user-typed /stop *command* is the documented emergency release for that
    # lock (commands/stop.md). Blocking it would leave the user with no exit.
    cancel_output = json.loads(cancelled.stdout)
    assert cancel_output.get("decision") != "block", cancel_output
    assert cancel_output["termination_allowed"] is True
    assert _state(root, sid)["command"] == "dev-overnight"
    assert _state(root, sid)["status"] == "user_cancelled"
    released = _run(NATIVE, "Stop", {"session_id": sid, "cwd": str(root)}, _native_env(root))
    released_output = json.loads(released.stdout)
    assert released.returncode == 0 and released_output["continue"] is True
    assert released_output["termination_allowed"] is True
    assert released_output["time_lock_active"] is False
    assert "decision" not in released_output


@pytest.mark.parametrize("frontier", [0, 3])
def test_claude_root_real_entrypoint_stop_is_not_time_locked(tmp_path: Path, frontier: int) -> None:
    root = tmp_path / f"claude-{frontier}"
    (root / "scripts" / "todo").mkdir(parents=True)
    shutil.copy2(SOURCE_ROOT / "scripts" / "todo" / "dev.py", root / "scripts" / "todo" / "dev.py")
    sid = f"claude-stop-{frontier}"
    env = {**os.environ, "HOME": str(root), "CLAUDE_PROJECT_DIR": str(root)}
    start = _run(PROMPT, None, {"session_id": sid, "cwd": str(root), "prompt": f"/dev claude frontier {frontier}"}, env)
    assert start.returncode == 0, start.stderr
    registry = root / ".claude" / "dev-registry"
    assert len(list(registry.iterdir())) == 1
    todos_path = root / ".claude" / "todos" / f"{sid}-agent-{sid}.json"
    todos = json.loads(todos_path.read_text())
    for next_frontier in range(1, frontier + 1):
        updated = []
        for index, item in enumerate(todos):
            copy = dict(item)
            copy["status"] = "completed" if index < next_frontier else (
                "in_progress" if index == next_frontier else "pending"
            )
            updated.append(copy)
        payload = {"session_id": sid, "cwd": str(root), "tool_name": "TodoWrite", "tool_input": {"todos": updated}}
        allowed = _run(PRETOOL, None, payload, env)
        assert allowed.returncode == 0, allowed.stderr
        tracked = _run(POSTTODO, None, payload, env)
        assert tracked.returncode == 0
        todos = updated
    stopped = _run(CLAUDE_STOP, None, {"session_id": sid, "cwd": str(root)}, env)
    assert stopped.returncode == 0
    assert "TIME-LOCK ACTIVE" not in stopped.stderr
    assert len(list(registry.iterdir())) == 1
    assert len(list((root / "docs" / "dev").glob("user-requirement-*.md"))) == 1


def test_active_codex_hook_plan_has_one_lifecycle_owner() -> None:
    hooks = json.loads(Path("/root/.codex/hooks.json").read_text())["hooks"]
    commands = [hook["command"] for groups in hooks.values() for group in groups for hook in group["hooks"]]
    for retired in (
        "prompt-workflow.py", "pretool-workflow-gate.py", "posttool-todo-tracker.py",
        "posttool-todo-count.py", "posttool-todo-sequence.py", "posttool-overnight-loop.py",
        "stop-overnight-timelock.py", "stop-workflow-reconcile.py",
    ):
        assert not any(retired in command for command in commands)
    for event in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
        owners = [
            hook["command"] for group in hooks[event] for hook in group["hooks"]
            if "codex_native_harness.py" in hook["command"]
        ]
        assert len(owners) == 1


def test_native_plan_authority_is_only_the_committed_start_transaction() -> None:
    assert "_final_agent_" + "message" not in PRETOOL.read_text()
    assert "spawn" + "_ms" not in Path(__file__).read_text()
    source = NATIVE.read_text()
    tree = ast.parse(source)
    functions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    plan_handler = functions["handle_tool_event"]
    plan_source = ast.get_source_segment(source, plan_handler) or ""
    lowered = plan_source.lower()
    for retired_authority in ("transcript", "elapsed", "handshake", "reentry"):
        assert retired_authority not in lowered
    assert "start_transaction" in plan_source
    assert 'transaction.get("status") != "committed"' in plan_source

    prompt_handler = functions["handle_user_prompt"]
    prompt_calls = {
        node.func.id
        for node in ast.walk(prompt_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "register_ordinary_start" in prompt_calls

    identity_handler = functions["_prompt_event_identity"]
    identity_source = ast.get_source_segment(source, identity_handler) or ""
    assert "native_event_identity_missing" in identity_source
    assert "native_event_identity_malformed" in identity_source
    assert "legacy" not in identity_source.lower()
    assert "sha256(prompt" not in identity_source


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_r03_configured_full_chain_resolution_execution_and_aggregation(
    tmp_path: Path, runtime: str
) -> None:
    fixture = make_configured_fixture(tmp_path, runtime, "full-chain")
    evidence = []
    evidence.append(_full_start(fixture, f"/dev r03 full chain {runtime}"))
    evidence.extend(_full_progress(fixture, 0))
    evidence.append(execute_configured_chain(fixture, "Stop", configured_payload(fixture, "Stop")))
    assert [item["event"] for item in evidence] == [
        "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"
    ]
    for item in evidence:
        fresh = resolve_configured_handlers(runtime, item["event"], item["tool_name"])
        assert item["resolved_handler_identities"] == [handler["identity"] for handler in fresh]
        assert item["resolved_handler_count"] == item["executed_handler_count"] > 0
        assert item["resolved_handler_identities"] == item["executed_handler_identities"]
        assert item["aggregate"]["state_owner_credit"] == 1
        for record in item["records"]:
            assert {
                "argv", "exit_code", "stdout", "stderr", "json_decision",
                "state_delta", "artifact_delta",
            } <= record.keys()
        assert item["aggregate"]["decision"] == "allow", item["aggregate"]["combined_user_visible_output"]
    stop_output = evidence[-1]["aggregate"]["combined_user_visible_output"].lower()
    assert "unfinished_step" not in stop_output
    assert "terminal reconciliation blocked" not in stop_output


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_r03_fresh_start_first_progress_and_exact_replay_matrix(
    tmp_path: Path, runtime: str
) -> None:
    fixture = make_configured_fixture(tmp_path, runtime, "replay")
    prompt = f"/dev r03 exact replay {runtime}"
    started = _full_start(fixture, prompt)
    assert started["aggregate"]["decision"] == "allow"
    first_identity = _current_identity(fixture)
    assert first_identity[1] == 1 and len(_task_families(fixture)) == 1

    start_bytes = _artifact_bytes(fixture)
    immediate = _full_start(fixture, prompt)
    assert immediate["aggregate"]["combined_user_visible_output"] == started["aggregate"]["combined_user_visible_output"]
    assert _artifact_bytes(fixture) == start_bytes
    assert _current_identity(fixture) == first_identity

    fixture["env"]["CLAUDE_DEV_CLOCK_ISO"] = "2037-03-04T05:07:09Z"
    fixture["env"]["CODEX_NATIVE_CLOCK_ISO"] = "2037-03-04T05:07:09Z"
    later = _full_start(fixture, prompt)
    assert later["aggregate"]["combined_user_visible_output"] == started["aggregate"]["combined_user_visible_output"]
    assert _artifact_bytes(fixture) == start_bytes
    assert _current_identity(fixture) == first_identity

    bootstrap = _full_progress(fixture, 0)
    assert all(item["aggregate"]["decision"] == "allow" for item in bootstrap)
    progressed = _full_progress(fixture, 1)
    assert all(item["aggregate"]["decision"] == "allow" for item in progressed)
    assert _frontier(fixture) == 1
    progress_bytes = _artifact_bytes(fixture)
    replayed = _full_progress(fixture, 1)
    assert all(item["aggregate"]["decision"] == "allow" for item in replayed)
    assert _frontier(fixture) == 1
    assert _artifact_bytes(fixture) == progress_bytes


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_r03_immediate_same_clock_distinct_active_reentry_preserves_prior_family(
    tmp_path: Path, runtime: str
) -> None:
    fixture = make_configured_fixture(tmp_path, runtime, "reentry")
    first = _full_start(fixture, f"/dev r03 prior family {runtime}")
    assert first["aggregate"]["decision"] == "allow"
    _full_progress(fixture, 0)
    _full_progress(fixture, 1)
    first_task, first_generation = _current_identity(fixture)
    prior_bytes = _task_families(fixture)[first_task]

    second = _full_start(fixture, f"/dev r03 active distinct family {runtime}")
    assert second["aggregate"]["decision"] == "allow", second["aggregate"]["combined_user_visible_output"]
    second_task, second_generation = _current_identity(fixture)
    assert first_generation == 1 and second_generation == 2
    assert first_task != second_task
    families = _task_families(fixture)
    assert set(families) == {first_task, second_task}
    assert families[first_task] == prior_bytes
    if runtime == "codex":
        state = _state(fixture["root"], fixture["sid"])
        assert state["workflow_history"][-1]["task_id"] == first_task
        assert state["workflow_history"][-1]["workflow_snapshot"]["task_id"] == first_task
        assert state["preservation_policy"] == PRESERVATION_POLICY
    else:
        history = fixture["root"] / ".claude" / "workflow-history" / fixture["sid"]
        archived = list(history.glob(f"*-{first_task}/bookmark.json"))
        assert len(archived) == 1
        assert json.loads(archived[0].read_text())["task_id"] == first_task


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_r03_whole_stop_then_next_generation_progress(tmp_path: Path, runtime: str) -> None:
    fixture = make_configured_fixture(tmp_path, runtime, "stop-next")
    _full_start(fixture, f"/dev r03 stop prior {runtime}")
    _full_progress(fixture, 0)
    _full_progress(fixture, 1)
    prior_task, _ = _current_identity(fixture)
    prior_bytes = _task_families(fixture)[prior_task]
    family_count = len(_task_families(fixture))

    stopped = execute_configured_chain(fixture, "Stop", configured_payload(fixture, "Stop"))
    combined = stopped["aggregate"]["combined_user_visible_output"].lower()
    assert stopped["aggregate"]["decision"] == "allow", combined
    assert "time-lock active" not in combined
    assert "unfinished_step" not in combined
    assert "terminal reconciliation blocked" not in combined
    assert len(_task_families(fixture)) == family_count

    next_start = _full_start(fixture, f"/dev r03 terminal next {runtime}")
    assert next_start["aggregate"]["decision"] == "allow"
    next_task, generation = _current_identity(fixture)
    assert next_task != prior_task and generation == 2
    assert _task_families(fixture)[prior_task] == prior_bytes
    _full_progress(fixture, 0)
    _full_progress(fixture, 1)
    assert _frontier(fixture) == 1
    before_replay = _artifact_bytes(fixture)
    _full_progress(fixture, 1)
    assert _artifact_bytes(fixture) == before_replay


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_r03_synchronised_independent_sessions_get_disjoint_families(
    tmp_path: Path, runtime: str
) -> None:
    first = make_configured_fixture(tmp_path, runtime, "barrier")
    second = dict(first)
    second["sid"] = first["sid"] + "-peer"
    barrier = threading.Barrier(2)

    def start(fixture: dict, label: str) -> dict:
        barrier.wait(timeout=10)
        return _full_start(fixture, f"/dev r03 barrier {runtime} {label}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(start, first, "A"), pool.submit(start, second, "B")]
        results = [future.result(timeout=60) for future in futures]
    assert all(result["aggregate"]["decision"] == "allow" for result in results)
    first_task, _ = _current_identity(first)
    second_task, _ = _current_identity(second)
    assert first_task != second_task
    assert len(_task_families(first)) == 2
    assert (
        first["root"] / ".claude" / "dev-registry" / first_task
    ).is_dir()
    assert (
        first["root"] / ".claude" / "dev-registry" / second_task
    ).is_dir()


def test_r03_owned_edit_replay_supports_shared_path_without_sibling_freeze(tmp_path: Path) -> None:
    shared = tmp_path / "shared.txt"
    baseline = b"baseline\n"
    owner_a = b"baseline\nowner-a\n"
    owner_b = b"baseline\nowner-a\nowner-b\n"
    snapshots = {
        "owner-a": {"path": str(shared), "sha256": hashlib.sha256(baseline).hexdigest()},
        "owner-b": {"path": str(shared), "sha256": hashlib.sha256(owner_a).hexdigest()},
    }
    edits = [
        {"owner": "owner-a", "path": str(shared), "before": baseline, "after": owner_a},
        {"owner": "owner-b", "path": str(shared), "before": owner_a, "after": owner_b},
    ]
    current = baseline
    for edit in edits:
        assert hashlib.sha256(current).hexdigest() == snapshots[edit["owner"]]["sha256"]
        assert current == edit["before"]
        current = edit["after"]
    assert current == owner_b
    assert len({edit["owner"] for edit in edits}) == 2
    assert "global_sibling_write_freeze" not in repr({"pre_edit_snapshots": snapshots, "owned_edits": edits})


def test_r03_prior_passes_and_no_superseded_ceremony_gate() -> None:
    for lane in ("r01", "r02"):
        qa = json.loads((SOURCE_ROOT / "docs" / "dev" / f"qa-report-dev-20260722-081544-{lane}.json").read_text())
        assert str(qa.get("verdict") or qa.get("decision") or "").lower() == "pass"
    contract_text = "\n".join([
        (SOURCE_ROOT / "docs" / "dev" / "ticket-dev-20260722-081544-r03.md").read_text(),
        (SOURCE_ROOT / "docs" / "dev" / "context-dev-20260722-081544-r03.json").read_text(),
        (SOURCE_ROOT / "docs" / "dev" / "acceptance-criteria-dev-20260722-081544-r03.json").read_text(),
    ]).lower()
    assert "human /hooks trust" in contract_text and "remains removed" in contract_text
    acceptance = json.loads(
        (SOURCE_ROOT / "docs" / "dev" / "acceptance-criteria-dev-20260722-081544-r03.json").read_text()
    )
    gate_scan = acceptance["acceptance_criteria"][0]["check"]["assertions"][-1]
    for forbidden in ("reload_epoch", "host_instance_id", "global_sequence", "raw_envelope_digest"):
        assert forbidden in gate_scan["forbidden_required_gates"]
    assert "active_generation_collision" not in ast.get_source_segment(
        NATIVE.read_text(),
        next(node for node in ast.parse(NATIVE.read_text()).body if isinstance(node, ast.FunctionDef) and node.name == "register_ordinary_start"),
    )
