"""LANE-B non-destructive receipt writers and serialized Stop coordinator."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
HOOKS = ROOT / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))
from lib import session_resources

spec = importlib.util.spec_from_file_location(
    "laneb_coordinator", HOOKS / "stop-workflow-coordinator.py"
)
assert spec and spec.loader
coordinator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = coordinator
spec.loader.exec_module(coordinator)

TRACKER = HOOKS / "posttool-todo-tracker.py"
TIMELOCK = HOOKS / "stop-overnight-timelock.py"


@pytest.fixture(autouse=True)
def _external_trusted_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trust_root = tmp_path.parent / f"{tmp_path.name}-laneb-trust"
    trust_root.mkdir(mode=0o700)
    monkeypatch.setenv(session_resources.TRUST_ROOT_ENV, str(trust_root))
    monkeypatch.setenv(session_resources.TRUST_KEY_ENV, "cd" * 32)
    yield
    shutil.rmtree(trust_root, ignore_errors=True)


def _binding(label: str, *, command: str = "dev", session: str | None = None) -> dict:
    claude = session or f"claude-{label}"
    resource = f"resource-{label}"
    workflow = f"workflow-{label}"
    if command == "dev-overnight":
        resource = f"overnight-resource-{label}"
        workflow = f"overnight:{claude}"
    return {
        "claude_session_id": claude,
        "resource_session_id": resource,
        "role": "dev",
        "dispatch_id": f"dispatch-{label}",
        "agent_id": f"dispatch-{label}",
        "command": command,
        "workflow_instance_id": workflow,
        "workflow_generation": 1,
        "spec_id": "20260808-035658",
    }


def _publish(root: Path, binding: dict) -> None:
    session_resources.publish_terminal_receipt(
        root,
        claude_session_id=binding["claude_session_id"],
        resource_session_id=binding["resource_session_id"],
        command=binding["command"],
        terminal_status="completed",
        workflow_instance_id=binding["workflow_instance_id"],
        workflow_generation=binding["workflow_generation"],
    )


def _tree_digest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {
        str(item.relative_to(path)): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(path.rglob("*"))
        if item.is_file() and not item.is_symlink()
    }


def _phase_script(root: Path, name: str, body: str = "") -> Path:
    path = root / f"phase-{name}.py"
    path.write_text(
        "import json,pathlib,sys,time\n"
        f"log=pathlib.Path({str(root / 'phase.log')!r})\n"
        f"log.write_text(log.read_text() + {name!r} + '\\n' if log.exists() else {name!r} + '\\n')\n"
        "payload=sys.stdin.buffer.read()\n" + body + "\n",
        encoding="utf-8",
    )
    return path


def _phases(root: Path, outcome: str = "allow") -> list:
    result = []
    for name in coordinator.PHASE_ORDER:
        body = ""
        timeout = 1.0
        if name == "timelock" and outcome == "invalid":
            body = "print(json.dumps({'decision':'mystery'}))"
        elif name == "coverage" and outcome == "block":
            body = "raise SystemExit(2)"
        elif name == "auto_commit" and outcome == "fail":
            body = "raise SystemExit(1)"
        elif name == "cleanup" and outcome == "timeout":
            body = "time.sleep(0.2)"
            timeout = 0.03
        script = _phase_script(root, name, body)
        result.append(coordinator.Phase(name, (sys.executable, str(script)), timeout))
    return result


def test_tracker_publishes_only_after_exact_canonical_completion(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    todo_dir = root / "scripts/todo"
    todo_dir.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/todo/dev.py", todo_dir / "dev.py")
    sid = "claude-tracker"
    task_id = "resource-tracker"
    binding = _binding("tracker", session=sid)
    binding["resource_session_id"] = task_id
    provisioned = session_resources.provision(root, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_text("preserve")
    before = _tree_digest(scratch)
    bookmark = {
        "command": "dev",
        "task_id": task_id,
        "workflow_instance_id": binding["workflow_instance_id"],
        "workflow_generation": 1,
    }
    bookmark_path = root / ".claude" / f"workflow-{sid}.json"
    bookmark_path.write_text(json.dumps(bookmark))
    canonical = json.loads(
        subprocess.run(
            [sys.executable, str(todo_dir / "dev.py")],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    completed = [{**item, "status": "completed"} for item in canonical]
    home = root / "home"
    todos_path = home / ".claude/todos" / f"{sid}-agent-{sid}.json"
    todos_path.parent.mkdir(parents=True)
    todos_path.write_text(json.dumps(completed))
    payload = {"session_id": sid, "tool_input": {"todos": completed}}
    result = subprocess.run(
        [sys.executable, str(TRACKER)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env={**os.environ, "HOME": str(home), "CLAUDE_PROJECT_DIR": str(root)},
    )
    assert result.returncode == 0
    receipt = root / ".claude/session-resources" / task_id / "terminal.json"
    assert json.loads(receipt.read_text())["terminal_status"] == "completed"
    assert not bookmark_path.exists() and not todos_path.exists()
    assert _tree_digest(scratch) == before


def test_tracker_short_all_completed_payload_is_nonterminal(tmp_path: Path) -> None:
    root = tmp_path / "project"
    todo_dir = root / "scripts/todo"
    todo_dir.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/todo/dev.py", todo_dir / "dev.py")
    sid = "claude-short"
    binding = _binding("short", session=sid)
    session_resources.provision(root, binding)
    bookmark = {
        "command": "dev",
        "task_id": binding["resource_session_id"],
        "workflow_instance_id": binding["workflow_instance_id"],
        "workflow_generation": 1,
    }
    bookmark_path = root / ".claude" / f"workflow-{sid}.json"
    bookmark_path.write_text(json.dumps(bookmark))
    one = [
        {
            "content": "Step 1: Parse development requirement",
            "activeForm": "Step 1: Parsing development requirement",
            "status": "completed",
        }
    ]
    result = subprocess.run(
        [sys.executable, str(TRACKER)],
        input=json.dumps({"session_id": sid, "tool_input": {"todos": one}}),
        text=True,
        capture_output=True,
        env={**os.environ, "HOME": str(root), "CLAUDE_PROJECT_DIR": str(root)},
    )
    assert result.returncode == 0 and bookmark_path.exists()
    assert not (
        root
        / ".claude/session-resources"
        / binding["resource_session_id"]
        / "terminal.json"
    ).exists()


def test_timelock_uses_exact_state_and_publishes_without_finalizing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    sid = "claude-overnight"
    binding = _binding("overnight", command="dev-overnight", session=sid)
    provisioned = session_resources.provision(root, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_text("preserve")
    before = _tree_digest(scratch)
    summary = root / "summary.md"
    summary.write_text("done")
    state = {
        "session_id": sid,
        "dev_registry_session_id": binding["resource_session_id"],
        "cycle_count": 0,
        "end_time": (datetime.now() - timedelta(seconds=5)).isoformat(),
        "final_summary_path": str(summary),
        "pm_retro_reports": ["retro"],
        "artifact_checkpoint_status": "checkpointed",
        "current_issues": [],
        "unresolved_issues": [],
    }
    state_path = root / ".claude" / f"overnight-state-{sid}.json"
    state_path.write_text(json.dumps(state))
    result = subprocess.run(
        [sys.executable, str(TIMELOCK)],
        input=json.dumps({"session_id": sid}),
        text=True,
        capture_output=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)},
    )
    assert result.returncode == 0, result.stderr
    receipt = (
        root
        / ".claude/session-resources"
        / binding["resource_session_id"]
        / "terminal.json"
    )
    assert json.loads(receipt.read_text())["terminal_status"] == "completed_by_deadline"
    assert _tree_digest(scratch) == before


@pytest.mark.parametrize("outcome", ["block", "fail", "timeout", "invalid"])
def test_non_success_phase_changes_zero_resource_bytes(
    tmp_path: Path, outcome: str
) -> None:
    root = tmp_path / outcome
    root.mkdir()
    binding = _binding(outcome)
    session_resources.provision(root, binding)
    _publish(root, binding)
    resource_tree = root / ".claude"
    before = _tree_digest(resource_tree)
    result, exit_code = coordinator.run_coordinator(
        {"session_id": binding["claude_session_id"], "cwd": str(root)},
        project_dir=root,
        environment={**os.environ, "CLAUDE_PROJECT_DIR": str(root)},
        phases=_phases(root, outcome),
    )
    assert exit_code == 2 and result["status"] == "blocked"
    assert result["finalizer_called"] is False
    assert _tree_digest(resource_tree) == before


def test_all_success_finalizes_only_exact_resource_session(tmp_path: Path) -> None:
    root = tmp_path / "success"
    root.mkdir()
    actor_a = _binding("A")
    actor_b = _binding("B")
    a = session_resources.provision(root, actor_a)
    b = session_resources.provision(root, actor_b)
    Path(a["scratch_path"], "A").write_text("A")
    Path(b["scratch_path"], "B").write_text("B")
    b_before = _tree_digest(Path(b["scratch_path"]))
    _publish(root, actor_a)
    result, exit_code = coordinator.run_coordinator(
        {"session_id": actor_a["claude_session_id"], "cwd": str(root)},
        project_dir=root,
        environment={**os.environ, "CLAUDE_PROJECT_DIR": str(root)},
        phases=_phases(root),
    )
    assert exit_code == 0 and result["status"] == "pass"
    assert result["finalizer_called"] is True
    assert not Path(a["scratch_path"]).exists()
    assert _tree_digest(Path(b["scratch_path"])) == b_before
    assert (root / "phase.log").read_text().splitlines() == list(
        coordinator.PHASE_ORDER
    )


def test_subagent_stop_runs_no_phase_and_never_finalizes(tmp_path: Path) -> None:
    root = tmp_path / "subagent"
    root.mkdir()
    binding = _binding("subagent")
    provisioned = session_resources.provision(root, binding)
    _publish(root, binding)
    before = _tree_digest(root / ".claude")
    result, exit_code = coordinator.run_coordinator(
        {"session_id": binding["claude_session_id"], "agent_id": "child"},
        project_dir=root,
        phases=_phases(root),
    )
    assert exit_code == 0 and result["status"] == "nonterminal"
    assert result["phases"] == [] and result["finalizer_called"] is False
    assert _tree_digest(root / ".claude") == before
    assert Path(provisioned["scratch_path"]).exists()


def test_receipt_before_delayed_barrier_signals_nothing_until_release(
    tmp_path: Path,
) -> None:
    root = tmp_path / "barrier"
    root.mkdir()
    binding = _binding("barrier")
    provisioned = session_resources.provision(root, binding)
    ready = Path(provisioned["scratch_path"]) / "ready"
    code = (
        "import pathlib,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        f"pathlib.Path({str(ready)!r}).write_text('ready');time.sleep(60)"
    )
    spawned = session_resources.spawn_owned(root, binding, [sys.executable, "-c", code])
    deadline = time.monotonic() + 3
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ready.exists()
    _publish(root, binding)
    barrier = root / "release"
    phase_list = _phases(root)
    coverage = _phase_script(
        root,
        "coverage-barrier",
        f"\nwhile not pathlib.Path({str(barrier)!r}).exists(): time.sleep(0.02)\n",
    )
    phase_list[1] = coordinator.Phase("coverage", (sys.executable, str(coverage)), 3.0)
    holder: dict = {}

    def run() -> None:
        holder["result"] = coordinator.run_coordinator(
            {"session_id": binding["claude_session_id"], "cwd": str(root)},
            project_dir=root,
            phases=phase_list,
        )

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.15)
    assert thread.is_alive()
    assert Path(f"/proc/{spawned['pid']}").exists()
    assert Path(provisioned["scratch_path"]).exists()
    barrier.write_text("release")
    thread.join(timeout=5)
    assert holder["result"][1] == 0
    assert not Path(provisioned["scratch_path"]).exists()


def test_explicit_empty_environment_does_not_fall_back_to_ambient_trust(
    tmp_path: Path,
) -> None:
    root = tmp_path / "explicit-empty"
    root.mkdir()
    binding = _binding("explicit-empty")
    session_resources.provision(root, binding)
    _publish(root, binding)
    phases = _phases(root)
    before = _tree_digest(root / ".claude")

    blocked, blocked_exit = coordinator.run_coordinator(
        {"session_id": binding["claude_session_id"], "cwd": str(root)},
        project_dir=root,
        environment={},
        phases=phases,
    )

    assert blocked_exit == 2
    assert blocked == {
        "status": "blocked",
        "reason": "resource_preflight_contract_error",
        "phases": [],
        "finalizer_called": False,
    }
    assert not (root / "phase.log").exists()
    assert _tree_digest(root / ".claude") == before

    passed, passed_exit = coordinator.run_coordinator(
        {"session_id": binding["claude_session_id"], "cwd": str(root)},
        project_dir=root,
        environment=None,
        phases=phases,
    )
    assert passed_exit == 0 and passed["status"] == "pass"
    assert (root / "phase.log").read_text().splitlines() == list(
        coordinator.PHASE_ORDER
    )


def test_preflight_precedes_phases_and_finalizes_retained_exact_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "preflight-order"
    root.mkdir()
    event_log = root / "phase.log"
    trust_environment = {
        session_resources.TRUST_KEY_ENV: "a5" * 32,
        session_resources.TRUST_ROOT_ENV: str(tmp_path / "private-trust"),
    }
    supplied_environment = {
        **trust_environment,
        "VISIBLE_PHASE_VALUE": "retained",
        "LANEB_UNRELATED": "ordinary",
    }
    pointer = {"resource_session_id": "resource-retained"}
    trust_calls: list[tuple[str, dict[str, str]]] = []

    def append_event(value: str) -> None:
        with event_log.open("a", encoding="utf-8") as handle:
            handle.write(value + "\n")

    def resolve(
        project_dir: Path,
        session_id: str,
        *,
        trust_environment: dict[str, str],
    ) -> dict:
        assert Path(project_dir) == root
        assert session_id == "claude-retained"
        trust_calls.append(("resolve", trust_environment))
        append_event("resolve")
        return pointer

    def finalize(
        project_dir: Path,
        *,
        claude_session_id: str,
        resource_session_id: str,
        trust_environment: dict[str, str],
    ) -> dict:
        assert Path(project_dir) == root
        assert claude_session_id == "claude-retained"
        assert resource_session_id == "resource-retained"
        trust_calls.append(("finalize", trust_environment))
        append_event(f"finalize:{resource_session_id}")
        return {"status": "pass", "idempotent": False}

    monkeypatch.setattr(
        coordinator.session_resources, "resolve_current_resource_session", resolve
    )
    monkeypatch.setattr(coordinator.session_resources, "finalize", finalize)

    phase_list = []
    for name in coordinator.PHASE_ORDER:
        observation = root / f"{name}-environment.json"
        body = (
            "import os\n"
            f"pathlib.Path({str(observation)!r}).write_text(json.dumps({{"
            f"'key':os.environ.get({session_resources.TRUST_KEY_ENV!r}),"
            f"'root':os.environ.get({session_resources.TRUST_ROOT_ENV!r}),"
            "'visible':os.environ.get('VISIBLE_PHASE_VALUE'),"
            "'ordinary':os.environ.get('LANEB_UNRELATED'),"
            "'coordinated':os.environ.get('LANEB_COORDINATED_STOP'),"
            "'project':os.environ.get('CLAUDE_PROJECT_DIR')}, sort_keys=True))"
        )
        script = _phase_script(root, name, body)
        phase_list.append(coordinator.Phase(name, (sys.executable, str(script))))

    original_run_phase = coordinator._run_phase

    def mutate_pointer_after_first_phase(*args: object, **kwargs: object) -> dict:
        result = original_run_phase(*args, **kwargs)
        phase = args[0] if args else kwargs["phase"]
        if phase.name == "timelock":
            pointer["resource_session_id"] = "resource-rebound"
        return result

    monkeypatch.setattr(coordinator, "_run_phase", mutate_pointer_after_first_phase)
    result, exit_code = coordinator.run_coordinator(
        {"session_id": "claude-retained", "cwd": str(root)},
        project_dir=root,
        environment=supplied_environment,
        phases=phase_list,
    )

    assert exit_code == 0 and result["resource_session_id"] == "resource-retained"
    assert event_log.read_text().splitlines() == [
        "resolve",
        *coordinator.PHASE_ORDER,
        "finalize:resource-retained",
    ]
    assert [item[0] for item in trust_calls] == ["resolve", "finalize"]
    assert trust_calls[0][1] == trust_environment == trust_calls[1][1]
    assert trust_calls[0][1] is trust_calls[1][1]
    for name in coordinator.PHASE_ORDER:
        observed = json.loads((root / f"{name}-environment.json").read_text())
        assert observed == {
            "coordinated": "1",
            "key": None,
            "ordinary": "ordinary",
            "project": str(root),
            "root": None,
            "visible": "retained",
        }


def test_preflight_failure_is_fixed_redacted_and_runs_zero_phases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "preflight-redaction"
    root.mkdir()
    trust_key = "b6" * 32
    trust_root = str(tmp_path / "secret-trust-root")
    observed_trust: list[dict[str, str]] = []

    def reject(*args: object, **kwargs: object) -> dict:
        observed_trust.append(dict(kwargs["trust_environment"]))
        raise RuntimeError(f"private failure {trust_key} {trust_root}")

    monkeypatch.setattr(
        coordinator.session_resources, "resolve_current_resource_session", reject
    )
    result, exit_code = coordinator.run_coordinator(
        {"session_id": "claude-redacted", "cwd": str(root)},
        project_dir=root,
        environment={
            session_resources.TRUST_KEY_ENV: trust_key,
            session_resources.TRUST_ROOT_ENV: trust_root,
        },
        phases=_phases(root),
    )

    serialized = json.dumps(result, sort_keys=True)
    assert exit_code == 2
    assert result == {
        "status": "blocked",
        "reason": "resource_preflight_contract_error",
        "phases": [],
        "finalizer_called": False,
    }
    assert trust_key not in serialized and trust_root not in serialized
    assert not (root / "phase.log").exists()
    assert observed_trust == [
        {
            session_resources.TRUST_KEY_ENV: trust_key,
            session_resources.TRUST_ROOT_ENV: trust_root,
        }
    ]


def test_finalizer_failure_is_fixed_and_cannot_echo_trust_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "finalizer-redaction"
    root.mkdir()
    trust_key = "c7" * 32
    trust_root = str(tmp_path / "finalizer-secret-root")

    monkeypatch.setattr(
        coordinator.session_resources,
        "resolve_current_resource_session",
        lambda *args, **kwargs: {"resource_session_id": "resource-redacted"},
    )
    monkeypatch.setattr(
        coordinator.session_resources,
        "finalize",
        lambda *args, **kwargs: {
            "status": "fail",
            "error_code": trust_key,
            "detail": trust_root,
        },
    )
    result, exit_code = coordinator.run_coordinator(
        {"session_id": "claude-redacted", "cwd": str(root)},
        project_dir=root,
        environment={
            session_resources.TRUST_KEY_ENV: trust_key,
            session_resources.TRUST_ROOT_ENV: trust_root,
        },
        phases=_phases(root),
    )

    serialized = json.dumps(result, sort_keys=True)
    assert exit_code == 2
    assert result["reason"] == "resource_finalize_failed"
    assert result["finalizer_called"] is True
    assert "finalizer" not in result
    assert trust_key not in serialized and trust_root not in serialized
    assert (root / "phase.log").read_text().splitlines() == list(
        coordinator.PHASE_ORDER
    )
