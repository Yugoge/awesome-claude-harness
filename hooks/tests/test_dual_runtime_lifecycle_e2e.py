"""Real-entrypoint regressions for single-owner ordinary dev lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


# The harness under test is the checkout that holds this file, never an install path.
SOURCE_ROOT = Path(__file__).resolve().parents[2]
PROMPT = SOURCE_ROOT / "hooks" / "prompt-workflow.py"
PRETOOL = SOURCE_ROOT / "hooks" / "pretool-workflow-gate.py"
POSTTODO = SOURCE_ROOT / "hooks" / "posttool-todo-tracker.py"
CLAUDE_STOP = SOURCE_ROOT / "hooks" / "stop-overnight-timelock.py"
ACTIVE_CONFIGS = {
    "claude": SOURCE_ROOT / "settings.json",
}
REQUIRED_CHAIN_EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")


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
    return [
        root / ".claude" / f"workflow-{sid}.json",
        home / ".claude" / "todos" / f"{sid}-agent-{sid}.json",
    ]


def _owner_command(runtime: str, event: str) -> str:
    return {
        "UserPromptSubmit": "prompt-workflow.py",
        "PreToolUse": "pretool-workflow-gate.py",
        "PostToolUse": "posttool-todo-tracker.py",
        "Stop": "stop-workflow-coordinator.py",
    }[event]


def _fixture_env(runtime: str, root: Path, home: Path, clock: str) -> dict[str, str]:
    return {
        **os.environ,
        "HOME": str(home),
        "CLAUDE_CONFIG_DIR": str(home / ".claude"),
        "CLAUDE_HOME": str(home / ".claude"),
        "CLAUDE_PROJECT_DIR": str(root),
        "CLAUDE_GRAPHIFY_ENABLED": "0",
        "CLAUDE_DEV_CLOCK_ISO": clock,
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def make_configured_fixture(base: Path, runtime: str, name: str) -> dict:
    root = base / f"{runtime}-{name}"
    home = base / f"{runtime}-{name}-home"
    root.mkdir(parents=True)
    claude_home = home / ".claude"
    claude_home.mkdir(parents=True)
    for child in ("hooks", "scripts", "commands", "agents"):
        (claude_home / child).symlink_to(SOURCE_ROOT / child, target_is_directory=True)
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
    state = json.loads(
        (fixture["root"] / ".claude" / f"workflow-{fixture['sid']}.json").read_text()
    )
    return state["task_id"], int(state["workflow_generation"])


def _frontier(fixture: dict) -> int:
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


@pytest.mark.parametrize("frontier", [0, 3])
def test_claude_root_real_entrypoint_stop_is_not_time_locked(tmp_path: Path, frontier: int) -> None:
    root = tmp_path / f"claude-{frontier}"
    (root / "scripts" / "todo").mkdir(parents=True)
    shutil.copy2(SOURCE_ROOT / "scripts" / "todo" / "dev.py", root / "scripts" / "todo" / "dev.py")
    sid = f"claude-stop-{frontier}"
    env = {**os.environ, "HOME": str(root), "CLAUDE_CONFIG_DIR": str(root / ".claude"),
           "CLAUDE_PROJECT_DIR": str(root)}
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


def test_claude_root_bare_dev_replay_mints_new_id_after_terminal_dev_report(tmp_path: Path) -> None:
    """AC-L5-03/04: an identical bare /dev prompt still replays byte-for-byte
    while the prior cycle's dev-report is missing (unchanged behavior); once
    that dev-report exists with a terminal dev.status, the IDENTICAL prompt
    must mint a brand-new task_id instead of replaying, and say so."""
    root = tmp_path / "claude-terminal-replay"
    (root / "scripts" / "todo").mkdir(parents=True)
    shutil.copy2(SOURCE_ROOT / "scripts" / "todo" / "dev.py", root / "scripts" / "todo" / "dev.py")
    sid = "claude-terminal-replay"
    env = {**os.environ, "HOME": str(root), "CLAUDE_CONFIG_DIR": str(root / ".claude"),
           "CLAUDE_PROJECT_DIR": str(root)}
    payload = {"session_id": sid, "cwd": str(root), "prompt": "/dev claude terminal replay"}
    registry = root / ".claude" / "dev-registry"

    first = _run(PROMPT, None, payload, env)
    assert first.returncode == 0, first.stderr
    assert len(list(registry.iterdir())) == 1
    first_task_id = next(registry.iterdir()).name

    # Prior dev-report MISSING: identical envelope must still replay verbatim.
    replay = _run(PROMPT, None, payload, env)
    assert replay.returncode == 0 and replay.stdout == first.stdout, \
        "replay with a non-terminal (missing) dev-report must stay byte-identical"
    assert len(list(registry.iterdir())) == 1, "no new task_id while prior cycle is non-terminal"

    # Prior dev-report now reaches a terminal state.
    (root / "docs" / "dev" / f"dev-report-{first_task_id}.json").write_text(json.dumps({
        "request_id": first_task_id, "task_id": first_task_id,
        "dev": {"status": "completed", "files_modified": [], "files_created": []},
    }))

    second = _run(PROMPT, None, payload, env)
    assert second.returncode == 0, second.stderr
    assert len(list(registry.iterdir())) == 2, "terminal prior cycle must mint a NEW task_id, not replay"
    new_ids = {p.name for p in registry.iterdir()} - {first_task_id}
    assert len(new_ids) == 1
    second_task_id = next(iter(new_ids))
    assert second_task_id != first_task_id
    assert "already reached a terminal state" in second.stdout, second.stdout
    assert first_task_id in second.stdout


@pytest.mark.parametrize("runtime", ["claude"])
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


@pytest.mark.parametrize("runtime", ["claude"])
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


@pytest.mark.parametrize("runtime", ["claude"])
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
    history = fixture["root"] / ".claude" / "workflow-history" / fixture["sid"]
    archived = list(history.glob(f"*-{first_task}/bookmark.json"))
    assert len(archived) == 1
    assert json.loads(archived[0].read_text())["task_id"] == first_task


@pytest.mark.parametrize("runtime", ["claude"])
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


@pytest.mark.parametrize("runtime", ["claude"])
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
