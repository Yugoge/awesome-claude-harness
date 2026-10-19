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


# The repair plan's tools/proto/crash.py (an instrument that dies before its pause
# check, exit 1) and slow.py (outlives its phase timeout). Neither writes phase.log.
CRASH_SOURCE = (
    "import sys\n"
    'raise ImportError("simulated: lib/overnight import failure before the pause check")\n'
)
SLOW_SOURCE = "import time; time.sleep(3)\n"
SLOW_TIMEOUT = 0.5  # below slow.py's 3 s sleep
# The phase a non-success outcome lands on when _phases names no target.
OUTCOME_PHASE = {
    "invalid": "timelock",
    "block": "coverage",
    "fail": "auto_commit",
    "timeout": "cleanup",
}
_OUTCOME_BODY = {
    "allow": "",
    "invalid": "print(json.dumps({'decision':'mystery'}))",
    "block": "raise SystemExit(2)",
    "fail": "raise SystemExit(1)",
    "timeout": "time.sleep(0.2)",
}


def _outcome_phase(root: Path, name: str, outcome: str):
    if outcome in ("crash", "slow"):
        script = root / f"{outcome}-{name}.py"
        script.write_text(CRASH_SOURCE if outcome == "crash" else SLOW_SOURCE, encoding="utf-8")
        timeout = SLOW_TIMEOUT if outcome == "slow" else 1.0
        return coordinator.Phase(name, (sys.executable, str(script)), timeout)
    if outcome == "missing":  # argv names a .py file that does not exist
        return coordinator.Phase(name, (sys.executable, str(root / f"missing-{name}.py")), 1.0)
    if outcome == "launch":  # the script exists, the interpreter does not
        script = _phase_script(root, name)
        return coordinator.Phase(name, (str(root / "no-such-interpreter"), str(script)), 1.0)
    script = _phase_script(root, name, _OUTCOME_BODY[outcome])
    timeout = 0.03 if outcome == "timeout" else 1.0
    return coordinator.Phase(name, (sys.executable, str(script)), timeout)


def _phases(root: Path, outcome: str = "allow", target: str | None = None) -> list:
    """The four phases in PHASE_ORDER, each logging its name to phase.log and
    allowing, except ``target`` (default OUTCOME_PHASE[outcome]), which runs
    ``outcome``: block (exit 2), fail (exit 1), timeout, invalid (a structured
    {"decision": "mystery"} on exit 0), crash, slow, missing or launch (error)."""
    target = target or OUTCOME_PHASE.get(outcome)
    return [
        _outcome_phase(root, name, outcome if name == target else "allow")
        for name in coordinator.PHASE_ORDER
    ]


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
    """P1 (TC-11): coverage exit 2 blocks; an auto_commit exit 1, a cleanup timeout
    and a timelock invalid decision with no typed command are recorded and allowed.
    No outcome reaches the finalizer or changes a resource byte."""
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
    target = OUTCOME_PHASE[outcome]
    assert result["finalizer_called"] is False
    if outcome == "block":
        assert exit_code == 2 and result["status"] == "blocked"
        assert result["failed_phase"] == "coverage"
        assert result["_relay"] == "failed_phase=coverage\n"
        assert [p["phase"] for p in result["phases"]] == ["timelock", "coverage"]
    else:
        assert exit_code == 0 and result["status"] == "pass"
        assert result["reason"] == "phase_failure_recorded"
        assert "failed_phase" not in result and "_relay" not in result
        assert [p["phase"] for p in result["phases"]] == list(coordinator.PHASE_ORDER)
        failed = [p for p in result["phases"] if p["status"] != "allow"]
        assert [(p["phase"], p["status"], p["failure"]) for p in failed] == [
            (
                target,
                outcome,
                {"fail": "exit code 1", "timeout": "timeout", "invalid": "invalid decision"}[outcome],
            )
        ]
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


# --------------------------------------------------------------------------
# P1 coordinator failure handling (TC-11, TC-39, B3.a, B3.b; acceptance 9, 9b)
# --------------------------------------------------------------------------

COORDINATOR = HOOKS / "stop-workflow-coordinator.py"
STOP_SESSION = "8b2f4c1d-6a3e-4f70-9d12-3c5e7a9b0f14"
# The prompts each transcript records: (command, args) is a typed slash command,
# a str a plain typed prompt. ACTIVE is stop_contract.active_command of each.
TRANSCRIPTS = {
    "dev-overnight": [("dev-overnight", "8h fix the flaky suite")],
    "dev-overnight-then-stop": [("dev-overnight", "8h fix the flaky suite"), ("stop", "")],
    "dev": [("dev", "fix the flaky suite")],
    "no-command": ["summarise the open issues"],
}
ACTIVE = {
    "dev-overnight": "dev-overnight",
    "dev-overnight-then-stop": "stop",
    "dev": "dev",
    "no-command": None,
}
# (status, returncode, failure) the result JSON records for each instrument failure.
INSTRUMENT_FAILURES = {
    "crash": ("fail", 1, "exit code 1"),
    "slow": ("timeout", None, "timeout"),
    "missing": ("fail", None, "missing file"),
    "launch": ("fail", None, "launch error"),
    "invalid": ("invalid", 0, "invalid decision"),
}
NOTICE = "Checkpoint snapshot refused: settings.json carries machine-local paths."


def _cli_record(index: int, record_type: str, **fields) -> dict:
    record = {
        "parentUuid": f"uuid-{index - 1:04d}" if index > 1 else None,
        "isSidechain": False,
        "type": record_type,
        "uuid": f"uuid-{index:04d}",
        "timestamp": f"2026-10-19T11:00:{index % 60:02d}.000Z",
        "userType": "external",
        "entrypoint": "cli",
        "cwd": "/opt/demo/toyproj",
        "sessionId": STOP_SESSION,
        "version": "2.1.303",
    }
    record.update(fields)
    return record


def _transcript(path: Path, prompts: list) -> Path:
    """A CLI-shaped main transcript: per typed prompt an enqueue/dequeue
    queue-operation pair, the human-typed user record (a slash command as
    <command-name>, followed by its isMeta command body) and an assistant reply."""
    records: list = []
    for prompt in prompts:
        if isinstance(prompt, tuple):
            name, args = prompt
            text = (
                f"<command-message>{name}</command-message>\n"
                f"<command-name>/{name}</command-name>\n"
                f"<command-args>{args}</command-args>"
            )
            queued = f"/{name} {args}".strip()
        else:
            name, text, queued = None, prompt, prompt
        stamp = f"2026-10-19T10:59:{len(records) % 60:02d}.000Z"
        records.append(
            {"type": "queue-operation", "operation": "enqueue", "timestamp": stamp,
             "sessionId": STOP_SESSION, "content": queued}
        )
        records.append(
            {"type": "queue-operation", "operation": "dequeue", "timestamp": stamp,
             "sessionId": STOP_SESSION}
        )
        index = len(records) + 1
        records.append(
            _cli_record(
                index, "user", promptId=f"prompt-{index:04d}",
                message={"role": "user", "content": text},
                permissionMode="default", origin={"kind": "human"},
            )
        )
        if name:
            records.append(
                _cli_record(
                    len(records) + 1, "user", isMeta=True,
                    promptId=f"prompt-{index:04d}",
                    message={"role": "user", "content": [
                        {"type": "text", "text": f"# /{name}\nFollow the steps."}
                    ]},
                )
            )
        records.append(
            _cli_record(
                len(records) + 1, "assistant",
                message={"role": "assistant", "content": [
                    {"type": "text", "text": "Working on it."}
                ]},
            )
        )
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _project(tmp_path: Path, transcript: str) -> tuple[Path, Path]:
    root = tmp_path / "project"
    root.mkdir()
    path = _transcript(tmp_path / "transcript.jsonl", TRANSCRIPTS[transcript])
    assert coordinator.stop_contract.active_command(path) == ACTIVE[transcript]
    return root, path


def _plain_environment(tmp_path: Path, root: Path) -> dict:
    """The ambient environment without the resource-broker trust keys (so no
    broker runs), HOME and CLAUDE_CONFIG_DIR pinned to a tmp home."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in coordinator.TRUST_ENVIRONMENT_KEYS
    }
    environment.update(
        {
            "HOME": str(home),
            "CLAUDE_CONFIG_DIR": str(home / ".claude"),
            "CLAUDE_PROJECT_DIR": str(root),
        }
    )
    return environment


def _stop(tmp_path: Path, root: Path, phases: list, transcript: Path) -> subprocess.CompletedProcess:
    """One Stop through the coordinator's main(), the phases passed through its
    LANEB_COORDINATOR_PHASES_JSON override."""
    environment = _plain_environment(tmp_path, root)
    environment["LANEB_COORDINATOR_PHASES_JSON"] = json.dumps(
        [{"name": p.name, "argv": list(p.argv), "timeout": p.timeout} for p in phases]
    )
    payload = {
        "session_id": STOP_SESSION,
        "transcript_path": str(transcript),
        "cwd": str(root),
        "hook_event_name": "Stop",
        "stop_hook_active": False,
    }
    return subprocess.run(
        [sys.executable, str(COORDINATOR)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(root),
        env=environment,
        timeout=60,
    )


def _logged(root: Path) -> list:
    log = root / "phase.log"
    return log.read_text().splitlines() if log.exists() else []


@pytest.mark.parametrize("failure", sorted(INSTRUMENT_FAILURES))
def test_timelock_instrument_failure_under_typed_dev_overnight_blocks_with_fixed_line(
    tmp_path: Path, failure: str
) -> None:
    """Acceptance 9: a crashing, slow, missing, unlaunchable or undecided timelock
    blocks a typed /dev-overnight Stop with only the fixed line naming /stop: no
    exception text, argv or phase stderr, and no later phase runs."""
    root, transcript = _project(tmp_path, "dev-overnight")
    phases = _phases(root, failure, target="timelock")
    status, returncode, reason = INSTRUMENT_FAILURES[failure]

    proc = _stop(tmp_path, root, phases, transcript)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "timelock instrument failure" in proc.stderr and "/stop" in proc.stderr
    assert proc.stderr == (
        f"timelock instrument failure: {reason}; the human can type /stop\n"
    )
    for leaked in ("ImportError", "simulated", "Traceback", "failed_phase=", phases[0].argv[-1]):
        assert leaked not in proc.stderr and leaked not in proc.stdout
    out = json.loads(proc.stdout)
    assert out["status"] == "blocked" and out["failed_phase"] == "timelock"
    assert out["finalizer_called"] is False and "_relay" not in out
    assert [
        (p["phase"], p["status"], p["returncode"], p["failure"]) for p in out["phases"]
    ] == [("timelock", status, returncode, reason)]
    assert _logged(root) == (["timelock"] if failure == "invalid" else [])


@pytest.mark.parametrize("failure", sorted(INSTRUMENT_FAILURES))
@pytest.mark.parametrize("transcript", ["dev-overnight-then-stop", "dev", "no-command"])
def test_timelock_instrument_failure_outside_dev_overnight_is_recorded_and_allowed(
    tmp_path: Path, transcript: str, failure: str
) -> None:
    """Acceptance 9: after a typed /stop (the phase still failing), under a typed
    /dev, or with no typed command, a timelock instrument failure is recorded in
    the result JSON and allowed, and the later phases run."""
    root, path = _project(tmp_path, transcript)
    status, returncode, reason = INSTRUMENT_FAILURES[failure]

    proc = _stop(tmp_path, root, _phases(root, failure, target="timelock"), path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stderr == ""
    out = json.loads(proc.stdout)
    assert out["status"] == "pass" and out["reason"] == "phase_failure_recorded"
    assert out["finalizer_called"] is False
    assert "failed_phase" not in out and "systemMessage" not in out
    assert [p["phase"] for p in out["phases"]] == list(coordinator.PHASE_ORDER)
    timelock, *later = out["phases"]
    assert (timelock["status"], timelock["returncode"], timelock["failure"]) == (
        status,
        returncode,
        reason,
    )
    assert all(p["status"] == "allow" and "failure" not in p for p in later)
    assert _logged(root)[-3:] == ["coverage", "auto_commit", "cleanup"]


@pytest.mark.parametrize(
    ("phase", "shape"),
    [("timelock", "exit-2"), ("timelock", "structured-block"), ("coverage", "exit-2")],
)
def test_block_relays_failed_phase_and_last_4kb_of_its_stderr(
    tmp_path: Path, phase: str, shape: str
) -> None:
    """A timelock exit 2, a structured timelock block on exit 0, and a coverage
    exit 2 block whatever the typed command, relaying failed_phase=<name> and the
    last 4 KB of that phase's stderr on the coordinator's stderr."""
    root, transcript = _project(tmp_path, "no-command")
    reason = f"{phase}: overnight window still open until 06:00"
    phase_stderr = "diagnostic padding line\n" * 300 + reason + "\n"
    assert len(phase_stderr) > 4096
    body = f"sys.stderr.write({phase_stderr!r})\n" + (
        f"print(json.dumps({{'decision': 'block', 'reason': {reason!r}}}))"
        if shape == "structured-block"
        else "raise SystemExit(2)"
    )
    phases = _phases(root)
    index = coordinator.PHASE_ORDER.index(phase)
    phases[index] = coordinator.Phase(
        phase, (sys.executable, str(_phase_script(root, phase, body))), 1.0
    )

    proc = _stop(tmp_path, root, phases, transcript)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert proc.stderr == f"failed_phase={phase}\n" + phase_stderr[-4096:]
    assert f"failed_phase={phase}" in proc.stderr and reason in proc.stderr
    assert "timelock instrument failure" not in proc.stderr
    out = json.loads(proc.stdout)
    assert out["status"] == "blocked" and out["failed_phase"] == phase
    assert out["finalizer_called"] is False and "_relay" not in out
    assert [p["phase"] for p in out["phases"]] == list(coordinator.PHASE_ORDER[: index + 1])
    assert (out["phases"][-1]["status"], out["phases"][-1]["returncode"]) == (
        "block",
        0 if shape == "structured-block" else 2,
    )
    assert _logged(root) == list(coordinator.PHASE_ORDER[: index + 1])


@pytest.mark.parametrize("failure", ["crash", "slow", "missing", "launch"])
@pytest.mark.parametrize("phase", ["coverage", "auto_commit", "cleanup"])
def test_non_timelock_failure_is_recorded_and_allowed_and_later_phases_run(
    tmp_path: Path, phase: str, failure: str
) -> None:
    """TC-11: coverage blocks only by exit 2. A coverage exit 1, an auto_commit
    exit 1, a cleanup timeout, and any other coverage, auto_commit or cleanup
    failure is recorded and allowed, also under a typed /dev-overnight; after an
    auto_commit failure the cleanup phase still runs."""
    root, transcript = _project(tmp_path, "dev-overnight")

    result, exit_code = coordinator.run_coordinator(
        {"session_id": STOP_SESSION, "cwd": str(root), "transcript_path": str(transcript)},
        project_dir=root,
        environment=_plain_environment(tmp_path, root),
        phases=_phases(root, failure, target=phase),
    )

    assert exit_code == 0
    assert result["status"] == "pass" and result["reason"] == "phase_failure_recorded"
    assert result["finalizer_called"] is False
    assert "failed_phase" not in result and "_relay" not in result
    assert [p["phase"] for p in result["phases"]] == list(coordinator.PHASE_ORDER)
    recorded = {
        p["phase"]: (p["status"], p["returncode"], p.get("failure"))
        for p in result["phases"]
    }
    assert recorded.pop(phase) == INSTRUMENT_FAILURES[failure]
    assert set(recorded.values()) == {("allow", 0, None)}
    # crash, slow, missing and launch never log; every other phase ran.
    assert _logged(root) == [name for name in coordinator.PHASE_ORDER if name != phase]


def test_default_phase_timeouts_fit_the_registered_stop_timeout() -> None:
    """Acceptance 9b: 30 + 30 + 120 + 30 = 210 s of phase timeouts under the
    coordinator Stop entry's 300 s registration timeout."""
    defaults = coordinator._default_phases()
    assert tuple(p.name for p in defaults) == coordinator.PHASE_ORDER
    total = sum(p.timeout for p in defaults)
    assert total == 210 < 300
    # The pre-launch missing-file check finds every default phase script.
    assert all(Path(coordinator._phase_script(p.argv)).is_file() for p in defaults)
    settings = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))
    entries = [
        hook
        for group in settings["hooks"]["Stop"]
        for hook in group["hooks"]
        if "stop-workflow-coordinator.py" in hook.get("command", "")
    ]
    assert len(entries) == 1
    assert entries[0]["timeout"] == 300
    assert total < entries[0]["timeout"]


@pytest.mark.parametrize("cleanup", ["allow", "slow"])
def test_passing_phase_notice_is_still_relayed(tmp_path: Path, cleanup: str) -> None:
    """P7: a passing phase's last-line systemMessage is shown as the coordinator's
    own, also when a later phase's failure is recorded."""
    root, transcript = _project(tmp_path, "dev")
    phases = _phases(root, cleanup, target="cleanup")
    body = f"print('snapshot refused')\nprint(json.dumps({{'systemMessage': {NOTICE!r}}}))"
    phases[2] = coordinator.Phase(
        "auto_commit", (sys.executable, str(_phase_script(root, "auto_commit", body))), 1.0
    )

    proc = _stop(tmp_path, root, phases, transcript)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stderr == ""
    out = json.loads(proc.stdout)
    assert out["systemMessage"] == NOTICE
    assert all("notice" not in p for p in out["phases"])
    assert out["status"] == "pass" and out["finalizer_called"] is False
    assert out["reason"] == (
        "resource_broker_not_configured" if cleanup == "allow" else "phase_failure_recorded"
    )
    assert out["phases"][2]["status"] == "allow"
    assert out["phases"][3]["status"] == ("allow" if cleanup == "allow" else "timeout")


@pytest.mark.parametrize("phase", ["auto_commit", "cleanup"])
def test_auto_commit_or_cleanup_exit_2_is_recorded_and_never_relayed(
    tmp_path: Path, phase: str
) -> None:
    """TC-11: only timelock and coverage may block. An auto_commit or cleanup exit
    2 under a typed /dev-overnight is recorded and allowed, its stderr is not
    relayed, and the later phases run."""
    root, transcript = _project(tmp_path, "dev-overnight")
    phases = _phases(root)
    index = coordinator.PHASE_ORDER.index(phase)
    body = f"sys.stderr.write({phase + ' diagnostic: snapshot write failed'!r})\nraise SystemExit(2)"
    phases[index] = coordinator.Phase(
        phase, (sys.executable, str(_phase_script(root, phase, body))), 1.0
    )

    proc = _stop(tmp_path, root, phases, transcript)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stderr == ""
    out = json.loads(proc.stdout)
    assert out["status"] == "pass" and out["reason"] == "phase_failure_recorded"
    assert out["finalizer_called"] is False and "failed_phase" not in out
    assert [p["phase"] for p in out["phases"]] == list(coordinator.PHASE_ORDER)
    recorded = out["phases"][index]
    assert recorded["returncode"] == 2 and recorded["status"] != "allow"
    assert "diagnostic" not in proc.stdout
    assert _logged(root) == list(coordinator.PHASE_ORDER)
